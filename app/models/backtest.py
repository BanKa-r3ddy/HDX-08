"""Pydantic contracts for persisted, reproducible paper backtests."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .trade import Trade


class BacktestConfig(BaseModel):
    """A daily historical replay configuration."""

    symbol: str = Field(min_length=1, max_length=20)
    start_date: date
    end_date: date
    initial_capital: float = Field(default=100_000.0, gt=0)
    strategy_name: str = "ema_trend_v1"
    include_news: bool = False

    @model_validator(mode="after")
    def valid_date_range(self) -> "BacktestConfig":
        """Reject impossible date ranges before any remote request."""
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be later than start_date")
        return self


class EquityPoint(BaseModel):
    """End-of-day virtual portfolio state during historical replay."""

    date: date
    portfolio_value: float
    cash: float
    open_positions: int
    daily_return: float


class PerformanceMetrics(BaseModel):
    """Standard performance measures calculated from closed virtual trades."""

    total_return_pct: float
    final_portfolio_value: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    average_profit: float | None
    average_loss: float | None
    largest_win: float | None
    largest_loss: float | None
    profit_factor: float | None
    maximum_drawdown_pct: float
    average_holding_time_seconds: float | None
    roi_pct: float


class BacktestResult(BaseModel):
    """Persistable result of a complete historical multi-agent replay."""

    model_config = ConfigDict(frozen=True)
    backtest_id: str
    created_at: datetime
    configuration: BacktestConfig
    summary: str
    trade_history: list[Trade]
    equity_curve: list[EquityPoint]
    performance_metrics: PerformanceMetrics
