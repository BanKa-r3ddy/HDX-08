"""Historical data, persistence, and metrics services for agent-based backtesting."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from time import sleep
from typing import Protocol

import pandas as pd
import yfinance as yf

from app.models.backtest import BacktestConfig, BacktestResult, EquityPoint, PerformanceMetrics
from app.models.trade import Trade


class HistoricalDataProvider(Protocol):
    """Extensible historical-data boundary; future adapters may add intraday data."""

    def get_history(self, symbol: str, start_date: str, end_date: str, interval: str = "1d") -> pd.DataFrame:
        """Return normalized OHLCV historical data."""


class YFinanceHistoricalDataProvider:
    """Daily yfinance provider with explicit timeout and transient retry handling."""

    def __init__(self, timeout_seconds: float = 10.0, max_retries: int = 3) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._logger = logging.getLogger("hdx08.backtest.yfinance")

    def get_history(self, symbol: str, start_date: str, end_date: str, interval: str = "1d") -> pd.DataFrame:
        """Fetch OHLCV data; end date is inclusive for the public backtest API."""
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                frame = yf.Ticker(symbol).history(start=start_date, end=end_date, interval=interval, timeout=self._timeout_seconds)
                if frame.empty:
                    raise ValueError("No historical market data was found")
                return frame[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except Exception as exc:
                last_error = exc
                self._logger.warning("backtest_history_attempt_failed", extra={"symbol": symbol, "attempt": attempt, "error": str(exc)})
                if attempt < self._max_retries:
                    sleep(0.25 * attempt)
        raise RuntimeError("Historical data provider is unavailable") from last_error


class BacktestRepository:
    """SQLite repository for compact, immutable completed-backtest records."""

    def __init__(self, database_path: Path) -> None:
        self._path = database_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS backtests (backtest_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, configuration TEXT NOT NULL, results TEXT NOT NULL)")

    def save(self, result: BacktestResult) -> None:
        """Persist a completed result JSON document."""
        with sqlite3.connect(self._path) as connection:
            connection.execute("INSERT INTO backtests(backtest_id, created_at, configuration, results) VALUES (?, ?, ?, ?)",
                               (result.backtest_id, result.created_at.isoformat(), result.configuration.model_dump_json(), result.model_dump_json()))

    def get(self, backtest_id: str) -> BacktestResult | None:
        """Load one completed backtest."""
        with sqlite3.connect(self._path) as connection:
            row = connection.execute("SELECT results FROM backtests WHERE backtest_id = ?", (backtest_id,)).fetchone()
        return BacktestResult.model_validate_json(row[0]) if row else None

    def list(self, limit: int = 50) -> list[BacktestResult]:
        """List newest completed backtests without loading raw market data."""
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute("SELECT results FROM backtests ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [BacktestResult.model_validate_json(row[0]) for row in rows]


class BacktestService:
    """Coordinates injected historical provider, replay agent, and SQLite storage."""

    def __init__(self, provider: HistoricalDataProvider, repository: BacktestRepository, agent: "BacktestRunner") -> None:
        self._provider, self._repository, self._agent = provider, repository, agent
        self._logger = logging.getLogger("hdx08.backtest")

    def run(self, configuration: BacktestConfig) -> BacktestResult:
        """Fetch daily history, replay it through agents, and persist the result."""
        history = self._provider.get_history(configuration.symbol, configuration.start_date.isoformat(), configuration.end_date.isoformat())
        result = self._agent.run(configuration, history)
        self._repository.save(result)
        self._logger.info("backtest_completed", extra={"backtest_id": result.backtest_id, "symbol": configuration.symbol, "trades": len(result.trade_history)})
        return result

    def get(self, backtest_id: str) -> BacktestResult | None:
        """Fetch one persisted completed backtest."""
        return self._repository.get(backtest_id)

    def list(self) -> list[BacktestResult]:
        """List completed persisted backtests."""
        return self._repository.list()


class BacktestRunner(Protocol):
    """Protocol keeping BacktestService independent of a specific replay agent."""

    def run(self, configuration: BacktestConfig, history: pd.DataFrame) -> BacktestResult:
        """Replay supplied daily candles and return a complete result."""


def calculate_metrics(initial_capital: float, trades: list[Trade], equity_curve: list[EquityPoint]) -> PerformanceMetrics:
    """Calculate reproducible performance metrics from closed virtual trades and equity."""
    closed = [trade for trade in trades if trade.pnl is not None]
    wins, losses = [float(trade.pnl) for trade in closed if trade.pnl > 0], [float(trade.pnl) for trade in closed if trade.pnl < 0]
    final_value = equity_curve[-1].portfolio_value if equity_curve else initial_capital
    peak, max_drawdown = initial_capital, 0.0
    for point in equity_curve:
        peak = max(peak, point.portfolio_value)
        if peak:
            max_drawdown = max(max_drawdown, ((peak - point.portfolio_value) / peak) * 100)
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    return PerformanceMetrics(total_return_pct=round(((final_value - initial_capital) / initial_capital) * 100, 4),
                              final_portfolio_value=round(final_value, 2), total_trades=len(closed), winning_trades=len(wins), losing_trades=len(losses),
                              win_rate_pct=round((len(wins) / len(closed)) * 100, 4) if closed else 0.0,
                              average_profit=round(sum(wins) / len(wins), 2) if wins else None,
                              average_loss=round(sum(losses) / len(losses), 2) if losses else None,
                              largest_win=round(max(wins), 2) if wins else None, largest_loss=round(min(losses), 2) if losses else None,
                              profit_factor=round(gross_profit / gross_loss, 4) if gross_loss else None,
                              maximum_drawdown_pct=round(max_drawdown, 4),
                              average_holding_time_seconds=round(sum(t.holding_time_seconds or 0 for t in closed) / len(closed), 3) if closed else None,
                              roi_pct=round(((final_value - initial_capital) / initial_capital) * 100, 4))
