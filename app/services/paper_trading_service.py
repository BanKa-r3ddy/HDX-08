"""SQLite-backed paper-trading engine with conservative virtual-risk controls."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import json
import logging
from pathlib import Path
import sqlite3
from time import sleep
from typing import Literal
from uuid import uuid4

from app.models.trade import PortfolioSnapshot, Trade, TradeStatus


class PaperTradingError(RuntimeError):
    """Raised for rejected virtual trades or unavailable local persistence."""


class TradeManager:
    """Manages virtual trades and balances; it has no broker or order integration."""

    STARTING_BALANCE = 100_000.0
    MAX_OPEN_TRADES = 5
    MAX_PORTFOLIO_ALLOCATION = 0.10
    MIN_CONFIDENCE = 70

    def __init__(self, database_path: Path, timeout_seconds: float = 5.0, max_retries: int = 3) -> None:
        if timeout_seconds <= 0 or max_retries < 1:
            raise ValueError("timeout_seconds must be positive and max_retries must be at least one")
        self._database_path = database_path
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._logger = logging.getLogger("hdx08.paper_trading")
        self._initialize()

    def open_trade(self, symbol: str, entry_price: float, confidence: int, reasoning: list[str],
                   stop_loss: float | None = None, take_profit: float | None = None, capital_limit: float | None = None) -> Trade:
        """Open a risk-limited virtual BUY position and reserve its cash amount."""
        if entry_price <= 0:
            raise PaperTradingError("Entry price must be positive")
        if confidence < self.MIN_CONFIDENCE:
            raise PaperTradingError("Virtual trade rejected: confidence must be at least 70")
        with self._connection() as connection:
            open_count = int(connection.execute("SELECT COUNT(*) FROM paper_trades WHERE status = 'OPEN'").fetchone()[0])
            if open_count >= self.MAX_OPEN_TRADES:
                raise PaperTradingError("Virtual trade rejected: maximum of five open trades reached")
            cash = self._cash_balance(connection)
            portfolio_value = self._portfolio_value(connection)
            allocation = min(cash, portfolio_value * self.MAX_PORTFOLIO_ALLOCATION, capital_limit if capital_limit is not None else float("inf"))
            quantity = int(allocation // entry_price)
            if quantity < 1:
                raise PaperTradingError("Virtual trade rejected: insufficient cash for one unit within the 10% limit")
            cost = round(quantity * entry_price, 2)
            now = datetime.now(timezone.utc)
            trade = Trade(trade_id=str(uuid4()), symbol=symbol.upper().strip(), entry_price=entry_price, quantity=quantity,
                          entry_time=now, confidence=confidence, reasoning=reasoning, stop_loss=stop_loss,
                          take_profit=take_profit, status="OPEN")
            connection.execute("UPDATE paper_portfolio SET cash_balance = cash_balance - ? WHERE id = 1", (cost,))
            connection.execute(
                "INSERT INTO paper_trades(trade_id, symbol, entry_price, quantity, entry_time, confidence, reasoning, stop_loss, take_profit, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (trade.trade_id, trade.symbol, trade.entry_price, trade.quantity, trade.entry_time.isoformat(), trade.confidence,
                 json.dumps(trade.reasoning), trade.stop_loss, trade.take_profit, trade.status),
            )
        self._logger.info("paper_trade_opened", extra={"trade_id": trade.trade_id, "symbol": trade.symbol, "quantity": trade.quantity})
        return trade

    def close_trade(self, trade_id: str, exit_price: float, status: TradeStatus = "CLOSED") -> Trade:
        """Close a virtual position, credit proceeds, and calculate P&L and ROI."""
        if exit_price <= 0:
            raise PaperTradingError("Exit price must be positive")
        if status not in ("CLOSED", "STOP LOSS", "TAKE PROFIT"):
            raise PaperTradingError("An open trade must close as CLOSED, STOP LOSS, or TAKE PROFIT")
        with self._connection() as connection:
            trade = self._fetch_trade(connection, trade_id)
            if trade.status != "OPEN":
                raise PaperTradingError("Virtual trade is already closed")
            exit_time = datetime.now(timezone.utc)
            pnl = round((exit_price - trade.entry_price) * trade.quantity, 2)
            invested = trade.entry_price * trade.quantity
            roi = round((pnl / invested) * 100, 4)
            holding_seconds = round((exit_time - trade.entry_time).total_seconds(), 3)
            connection.execute("UPDATE paper_portfolio SET cash_balance = cash_balance + ? WHERE id = 1", (round(exit_price * trade.quantity, 2),))
            connection.execute("UPDATE paper_trades SET exit_price=?, exit_time=?, pnl=?, roi=?, holding_time_seconds=?, status=? WHERE trade_id=?",
                               (exit_price, exit_time.isoformat(), pnl, roi, holding_seconds, status, trade_id))
        closed = trade.model_copy(update={"exit_price": exit_price, "exit_time": exit_time, "pnl": pnl, "roi": roi,
                                          "holding_time_seconds": holding_seconds, "status": status})
        self._logger.info("paper_trade_closed", extra={"trade_id": trade_id, "status": status, "pnl": pnl})
        return closed

    def update_trade(self, trade_id: str, current_price: float) -> Trade:
        """Evaluate stop-loss/take-profit levels and close a triggered virtual trade."""
        trade = self.get_trade(trade_id)
        if trade.status != "OPEN":
            return trade
        if trade.stop_loss is not None and current_price <= trade.stop_loss:
            return self.close_trade(trade_id, current_price, "STOP LOSS")
        if trade.take_profit is not None and current_price >= trade.take_profit:
            return self.close_trade(trade_id, current_price, "TAKE PROFIT")
        return trade

    def get_open_positions(self) -> list[Trade]:
        """Return current virtual positions."""
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM paper_trades WHERE status = 'OPEN' ORDER BY entry_time DESC").fetchall()
        return [self._trade_from_row(row) for row in rows]

    def get_trade_history(self) -> list[Trade]:
        """Return virtual trade history, newest first."""
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM paper_trades ORDER BY entry_time DESC").fetchall()
        return [self._trade_from_row(row) for row in rows]

    def get_trade(self, trade_id: str) -> Trade:
        """Return a single virtual trade or raise a meaningful lookup error."""
        with self._connection() as connection:
            return self._fetch_trade(connection, trade_id)

    def get_portfolio(self) -> PortfolioSnapshot:
        """Return virtual balances, entry-value positions, and realized daily P&L."""
        with self._connection() as connection:
            starting, cash = connection.execute("SELECT starting_balance, cash_balance FROM paper_portfolio WHERE id = 1").fetchone()
            positions = [self._trade_from_row(row) for row in connection.execute("SELECT * FROM paper_trades WHERE status = 'OPEN'").fetchall()]
            today = datetime.now(timezone.utc).date().isoformat()
            daily_pnl = float(connection.execute("SELECT COALESCE(SUM(pnl), 0) FROM paper_trades WHERE exit_time LIKE ?", (f"{today}%",)).fetchone()[0])
        position_value = sum(trade.entry_price * trade.quantity for trade in positions)
        return PortfolioSnapshot(starting_balance=float(starting), cash_balance=round(float(cash), 2), open_positions=positions,
                                 portfolio_value=round(float(cash) + position_value, 2), daily_pnl=round(daily_pnl, 2))

    def reset(self, initial_balance: float | None = None) -> PortfolioSnapshot:
        """Clear virtual trades and restore the requested virtual balance."""
        balance = self.STARTING_BALANCE if initial_balance is None else initial_balance
        if balance <= 0:
            raise PaperTradingError("Initial virtual balance must be positive")
        with self._connection() as connection:
            connection.execute("DELETE FROM paper_trades")
            connection.execute("UPDATE paper_portfolio SET starting_balance=?, cash_balance=? WHERE id = 1", (balance, balance))
        self._logger.info("paper_portfolio_reset")
        return self.get_portfolio()

    def _initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS paper_portfolio (id INTEGER PRIMARY KEY CHECK(id = 1), starting_balance REAL NOT NULL, cash_balance REAL NOT NULL)")
            connection.execute("INSERT OR IGNORE INTO paper_portfolio(id, starting_balance, cash_balance) VALUES (1, ?, ?)", (self.STARTING_BALANCE, self.STARTING_BALANCE))
            connection.execute("CREATE TABLE IF NOT EXISTS paper_trades (trade_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, entry_price REAL NOT NULL, quantity INTEGER NOT NULL, entry_time TEXT NOT NULL, confidence INTEGER NOT NULL, reasoning TEXT NOT NULL, stop_loss REAL, take_profit REAL, status TEXT NOT NULL, exit_price REAL, exit_time TEXT, pnl REAL, roi REAL, holding_time_seconds REAL)")

    @contextmanager
    def _connection(self):
        """Open a SQLite connection with busy timeout and retry transient locks."""
        last_error: sqlite3.Error | None = None
        connection: sqlite3.Connection | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                connection = sqlite3.connect(self._database_path, timeout=self._timeout_seconds)
                connection.execute(f"PRAGMA busy_timeout = {int(self._timeout_seconds * 1000)}")
                break
            except sqlite3.OperationalError as exc:
                last_error = exc
                if attempt == self._max_retries or "locked" not in str(exc).lower():
                    raise
                self._logger.warning("paper_sqlite_retry", extra={"attempt": attempt, "error": str(exc)})
                sleep(0.1 * attempt)
        if connection is None:
            raise PaperTradingError("Paper-trading database is unavailable") from last_error
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _fetch_trade(self, connection: sqlite3.Connection, trade_id: str) -> Trade:
        row = connection.execute("SELECT * FROM paper_trades WHERE trade_id = ?", (trade_id,)).fetchone()
        if row is None:
            raise PaperTradingError("Virtual trade was not found")
        return self._trade_from_row(row)

    @staticmethod
    def _trade_from_row(row: tuple[object, ...]) -> Trade:
        return Trade(trade_id=str(row[0]), symbol=str(row[1]), entry_price=float(row[2]), quantity=int(row[3]),
                     entry_time=datetime.fromisoformat(str(row[4])), confidence=int(row[5]), reasoning=json.loads(str(row[6])),
                     stop_loss=float(row[7]) if row[7] is not None else None, take_profit=float(row[8]) if row[8] is not None else None,
                     status=row[9], exit_price=float(row[10]) if row[10] is not None else None,
                     exit_time=datetime.fromisoformat(str(row[11])) if row[11] else None,
                     pnl=float(row[12]) if row[12] is not None else None, roi=float(row[13]) if row[13] is not None else None,
                     holding_time_seconds=float(row[14]) if row[14] is not None else None)

    def _cash_balance(self, connection: sqlite3.Connection) -> float:
        return float(connection.execute("SELECT cash_balance FROM paper_portfolio WHERE id = 1").fetchone()[0])

    def _portfolio_value(self, connection: sqlite3.Connection) -> float:
        cash = self._cash_balance(connection)
        entries = float(connection.execute("SELECT COALESCE(SUM(entry_price * quantity), 0) FROM paper_trades WHERE status = 'OPEN'").fetchone()[0])
        return cash + entries


class PaperTradingService:
    """Application-facing facade exposing a single injected TradeManager."""

    def __init__(self, trade_manager: TradeManager) -> None:
        self.trade_manager = trade_manager
