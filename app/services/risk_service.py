"""Configurable SQLite-backed portfolio intelligence and virtual-trade risk checks."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import logging
from math import floor
from pathlib import Path
import sqlite3
from time import sleep
from typing import Protocol

from app.models.portfolio import PortfolioStats, RiskConfig, RiskReport, SectorExposure
from app.models.trade import Trade
from app.services.paper_trading_service import PaperTradingService


class SectorClassifier(Protocol):
    """Replaceable exchange- and market-aware sector classification boundary."""

    def classify(self, symbol: str) -> str:
        """Return a stable sector label for an instrument."""


class CorrelationChecker(Protocol):
    """Future correlation service boundary; no market correlation is calculated yet."""

    def is_correlated(self, symbol: str, open_symbols: list[str]) -> bool | None:
        """Return correlation violation, no violation, or None when unavailable."""


class StaticSectorClassifier:
    """Small default US-equity mapping, replaceable for other exchanges and markets."""

    _SECTORS = {"AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "GOOGL": "Communication Services",
                "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary", "JPM": "Financials", "XOM": "Energy"}

    def classify(self, symbol: str) -> str:
        return self._SECTORS.get(symbol.upper(), "Unclassified")


class PositionSizer(Protocol):
    """Extension point for sizing approaches such as Kelly Criterion."""

    def capital(self, portfolio_value: float, confidence: int, config: RiskConfig, volatility: float) -> float | None:
        """Return desired virtual capital, or None when the model is unavailable."""


class FixedAllocationSizer:
    def capital(self, portfolio_value: float, confidence: int, config: RiskConfig, volatility: float) -> float:
        return portfolio_value * config.fixed_allocation


class ConfidenceWeightedSizer:
    def capital(self, portfolio_value: float, confidence: int, config: RiskConfig, volatility: float) -> float:
        base = portfolio_value * config.max_stock_allocation * (max(0, min(confidence, 100)) / 100)
        return base * max(0.25, 1 - max(volatility, 0))


class RiskPercentageSizer:
    def capital(self, portfolio_value: float, confidence: int, config: RiskConfig, volatility: float) -> float:
        return portfolio_value * config.risk_per_trade * max(0.25, 1 - max(volatility, 0))


class KellySizer:
    """Interface placeholder until a validated probability/odds source is available."""

    def capital(self, portfolio_value: float, confidence: int, config: RiskConfig, volatility: float) -> None:
        return None


class RiskRepository:
    """Persists portfolio snapshots, risk reports, exposures, and metrics with SQLite retries."""

    def __init__(self, database_path: Path, timeout_seconds: float = 5.0, max_retries: int = 3) -> None:
        self._path, self._timeout, self._retries = database_path, timeout_seconds, max_retries
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("hdx08.risk.repository")
        with self._connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS portfolio_snapshots (timestamp TEXT NOT NULL, portfolio_value REAL NOT NULL, cash REAL NOT NULL, invested REAL NOT NULL, realized_pnl REAL NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS risk_reports (timestamp TEXT NOT NULL, report TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS exposure_history (timestamp TEXT NOT NULL, sectors TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS portfolio_metrics (timestamp TEXT NOT NULL, metrics TEXT NOT NULL)")

    def save(self, report: RiskReport, stats: PortfolioStats) -> None:
        """Store one decision-time portfolio state atomically."""
        now = report.created_at.isoformat()
        with self._connection() as connection:
            connection.execute("INSERT INTO portfolio_snapshots VALUES (?, ?, ?, ?, ?)", (now, stats.portfolio_value, stats.cash, stats.invested_capital, stats.realized_pnl))
            connection.execute("INSERT INTO risk_reports VALUES (?, ?)", (now, report.model_dump_json()))
            connection.execute("INSERT INTO exposure_history VALUES (?, ?)", (now, json.dumps([item.model_dump() for item in stats.sector_allocation])))
            connection.execute("INSERT INTO portfolio_metrics VALUES (?, ?)", (now, stats.model_dump_json()))

    def latest_report(self) -> RiskReport | None:
        with self._connection() as connection:
            row = connection.execute("SELECT report FROM risk_reports ORDER BY timestamp DESC LIMIT 1").fetchone()
        return RiskReport.model_validate_json(row[0]) if row else None

    def snapshots(self) -> list[tuple[datetime, float]]:
        with self._connection() as connection:
            rows = connection.execute("SELECT timestamp, portfolio_value FROM portfolio_snapshots ORDER BY timestamp").fetchall()
        return [(datetime.fromisoformat(row[0]), float(row[1])) for row in rows]

    @contextmanager
    def _connection(self):
        last_error: sqlite3.Error | None = None
        connection: sqlite3.Connection | None = None
        for attempt in range(1, self._retries + 1):
            try:
                connection = sqlite3.connect(self._path, timeout=self._timeout)
                connection.execute(f"PRAGMA busy_timeout = {int(self._timeout * 1000)}")
                break
            except sqlite3.OperationalError as exc:
                last_error = exc
                if attempt == self._retries:
                    raise
                sleep(0.1 * attempt)
        if connection is None:
            raise RuntimeError("Risk database is unavailable") from last_error
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


class RiskService:
    """Evaluates virtual portfolio risk without placing or routing any order."""

    def __init__(self, paper_trading: PaperTradingService, repository: RiskRepository, configuration: RiskConfig,
                 sector_classifier: SectorClassifier | None = None, correlation_checker: CorrelationChecker | None = None,
                 sizers: dict[str, PositionSizer] | None = None) -> None:
        self._paper, self._repository, self._config = paper_trading, repository, configuration
        self._classifier, self._correlation = sector_classifier or StaticSectorClassifier(), correlation_checker
        self._sizers = sizers or {"fixed": FixedAllocationSizer(), "confidence_weighted": ConfidenceWeightedSizer(),
                                  "risk_percentage": RiskPercentageSizer(), "kelly": KellySizer()}
        self._logger = logging.getLogger("hdx08.risk")

    def evaluate(self, symbol: str, price: float, confidence: int, action: str = "BUY", volatility: float = 0.0) -> RiskReport:
        """Approve/reject only a prospective virtual BUY using configurable portfolio limits."""
        stats = self.get_portfolio_stats()
        now = datetime.now(timezone.utc)
        if action.upper() != "BUY":
            report = RiskReport(approved=True, risk_score=0, recommended_quantity=0, recommended_capital=0, warnings=[], reason="No new virtual BUY requires risk approval.", created_at=now)
            self._repository.save(report, stats)
            return report
        warnings: list[str] = []
        if price <= 0:
            warnings.append("Current market price is unavailable.")
        if confidence < self._config.minimum_confidence:
            warnings.append("Confidence is below the minimum paper-trading threshold.")
        desired = self._sizers[self._config.sizing_model].capital(stats.portfolio_value, confidence, self._config, volatility)
        if desired is None:
            warnings.append("Kelly sizing is an interface only and is not configured.")
            desired = 0.0
        sector = self._classifier.classify(symbol)
        open_trades = self._paper.trade_manager.get_open_positions()
        invested_by_symbol = sum(trade.entry_price * trade.quantity for trade in open_trades if trade.symbol == symbol.upper())
        sectors = self._sector_capital(open_trades)
        desired = min(desired, stats.portfolio_value * self._config.max_stock_allocation - invested_by_symbol, stats.cash)
        desired = max(0.0, desired)
        if len(open_trades) >= self._config.max_positions and not any(trade.symbol == symbol.upper() for trade in open_trades):
            warnings.append("Maximum concurrent virtual positions reached.")
        if invested_by_symbol + desired > stats.portfolio_value * self._config.max_stock_allocation + 0.01:
            warnings.append("Maximum allocation per stock would be exceeded.")
        if sectors.get(sector, 0.0) + desired > stats.portfolio_value * self._config.max_sector_allocation + 0.01:
            warnings.append(f"Maximum {sector} sector allocation would be exceeded.")
        if stats.invested_capital + desired > stats.portfolio_value * self._config.max_daily_exposure + 0.01:
            warnings.append("Maximum daily portfolio exposure would be exceeded.")
        if stats.cash - desired < stats.portfolio_value * self._config.minimum_cash_reserve - 0.01:
            warnings.append("Minimum cash reserve would be breached.")
        if stats.largest_drawdown_pct / 100 >= self._config.max_drawdown:
            warnings.append("Maximum drawdown threshold has been reached.")
        if self._correlation is not None and self._correlation.is_correlated(symbol, [trade.symbol for trade in open_trades]):
            warnings.append("Correlation check rejected the proposed position.")
        quantity = floor(desired / price) if price > 0 else 0
        if quantity < 1:
            warnings.append("Recommended capital cannot purchase one virtual unit.")
        approved = not warnings
        capital = round(quantity * price, 2) if approved else 0.0
        report = RiskReport(approved=approved, risk_score=min(100, len(warnings) * 20 + int(max(volatility, 0) * 20)),
                            recommended_quantity=quantity if approved else 0, recommended_capital=capital, warnings=warnings,
                            reason="Portfolio allocation is within configured limits." if approved else "Virtual trade rejected by portfolio risk controls.", created_at=now)
        self._repository.save(report, stats)
        self._logger.info("risk_evaluated", extra={"symbol": symbol, "approved": approved, "risk_score": report.risk_score, "warnings": len(warnings)})
        return report

    def get_portfolio_stats(self) -> PortfolioStats:
        """Return portfolio, exposure, return, and drawdown statistics from virtual trades/snapshots."""
        snapshot = self._paper.trade_manager.get_portfolio()
        history = self._paper.trade_manager.get_trade_history()
        open_trades, closed_trades = snapshot.open_positions, [trade for trade in history if trade.status != "OPEN"]
        invested = sum(trade.entry_price * trade.quantity for trade in open_trades)
        realized = sum(trade.pnl or 0 for trade in closed_trades)
        sector_capital = self._sector_capital(open_trades)
        sectors = [SectorExposure(sector=sector, invested_capital=round(capital, 2), exposure_pct=round((capital / snapshot.portfolio_value) * 100, 4) if snapshot.portfolio_value else 0.0) for sector, capital in sorted(sector_capital.items())]
        returns = self._returns()
        values = [value for _, value in self._repository.snapshots()] + [snapshot.portfolio_value]
        peak, drawdown = snapshot.starting_balance, 0.0
        for value in values:
            peak = max(peak, value)
            drawdown = max(drawdown, ((peak - value) / peak) * 100 if peak else 0.0)
        return PortfolioStats(portfolio_value=snapshot.portfolio_value, cash=snapshot.cash_balance, invested_capital=round(invested, 2),
                              unrealized_pnl=0.0, realized_pnl=round(realized, 2), daily_return=returns["daily"], weekly_return=returns["weekly"],
                              monthly_return=returns["monthly"], annual_return=returns["annual"], largest_position=round(max((trade.entry_price * trade.quantity for trade in open_trades), default=0.0), 2),
                              largest_drawdown_pct=round(drawdown, 4), exposure_pct=round((invested / snapshot.portfolio_value) * 100, 4) if snapshot.portfolio_value else 0.0,
                              open_positions=len(open_trades), closed_positions=len(closed_trades), sector_allocation=sectors)

    def get_sector_exposure(self) -> list[SectorExposure]:
        """Return current classified sector exposure."""
        return self.get_portfolio_stats().sector_allocation

    def get_open_positions(self) -> list[Trade]:
        """Expose current virtual positions without leaking paper-service internals."""
        return self._paper.trade_manager.get_open_positions()

    def latest_report(self) -> RiskReport:
        """Return latest persisted report, or a baseline no-action report."""
        return self._repository.latest_report() or self.evaluate("PORTFOLIO", 1.0, 100, action="HOLD")

    def _sector_capital(self, trades: list[Trade]) -> dict[str, float]:
        values: dict[str, float] = {}
        for trade in trades:
            sector = self._classifier.classify(trade.symbol)
            values[sector] = values.get(sector, 0.0) + trade.entry_price * trade.quantity
        return values

    def _returns(self) -> dict[str, float]:
        snapshots = self._repository.snapshots()
        if len(snapshots) < 2:
            return {"daily": 0.0, "weekly": 0.0, "monthly": 0.0, "annual": 0.0}
        latest_time, latest = snapshots[-1]
        def period(days: int) -> float:
            candidates = [value for timestamp, value in snapshots if (latest_time - timestamp).days >= days]
            base = candidates[-1] if candidates else snapshots[0][1]
            return round(((latest - base) / base) * 100, 4) if base else 0.0
        return {"daily": period(1), "weekly": period(7), "monthly": period(30), "annual": period(365)}
