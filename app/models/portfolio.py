"""Portfolio, exposure, and risk Pydantic contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RiskConfig(BaseModel):
    """Injected configurable portfolio limits; services never hardcode risk values."""

    max_positions: int = Field(default=5, ge=1)
    max_stock_allocation: float = Field(default=0.10, gt=0, le=1)
    max_sector_allocation: float = Field(default=0.30, gt=0, le=1)
    max_daily_exposure: float = Field(default=0.80, gt=0, le=1)
    max_drawdown: float = Field(default=0.15, gt=0, le=1)
    minimum_cash_reserve: float = Field(default=0.20, ge=0, le=1)
    risk_per_trade: float = Field(default=0.02, gt=0, le=1)
    minimum_confidence: int = Field(default=70, ge=0, le=100)
    sizing_model: Literal["fixed", "confidence_weighted", "risk_percentage", "kelly"] = "confidence_weighted"
    fixed_allocation: float = Field(default=0.05, gt=0, le=1)


class RiskReport(BaseModel):
    """The only output used to approve or reject a virtual trade."""

    model_config = ConfigDict(frozen=True)
    approved: bool
    risk_score: int = Field(ge=0, le=100)
    recommended_quantity: int = Field(ge=0)
    recommended_capital: float = Field(ge=0)
    warnings: list[str]
    reason: str
    created_at: datetime


class SectorExposure(BaseModel):
    """Invested virtual capital attributed to one classified sector."""

    sector: str
    invested_capital: float
    exposure_pct: float


class PortfolioStats(BaseModel):
    """Portfolio-level virtual-performance statistics used by the risk layer."""

    model_config = ConfigDict(frozen=True)
    portfolio_value: float
    cash: float
    invested_capital: float
    unrealized_pnl: float
    realized_pnl: float
    daily_return: float
    weekly_return: float
    monthly_return: float
    annual_return: float
    largest_position: float
    largest_drawdown_pct: float
    exposure_pct: float
    open_positions: int
    closed_positions: int
    sector_allocation: list[SectorExposure]
