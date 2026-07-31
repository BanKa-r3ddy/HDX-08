"""Paper-trading domain models; these represent virtual positions only."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TradeStatus = Literal["OPEN", "CLOSED", "STOP LOSS", "TAKE PROFIT"]


class Trade(BaseModel):
    """A virtual paper-trading position with entry and optional exit data."""

    model_config = ConfigDict(frozen=True)
    trade_id: str
    symbol: str
    entry_price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    entry_time: datetime
    confidence: int = Field(ge=0, le=100)
    reasoning: list[str]
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    status: TradeStatus
    exit_price: float | None = None
    exit_time: datetime | None = None
    pnl: float | None = None
    roi: float | None = None
    holding_time_seconds: float | None = None


class PortfolioSnapshot(BaseModel):
    """Current virtual cash, position valuation, and realized daily P&L."""

    model_config = ConfigDict(frozen=True)
    starting_balance: float
    cash_balance: float
    open_positions: list[Trade]
    portfolio_value: float
    daily_pnl: float
