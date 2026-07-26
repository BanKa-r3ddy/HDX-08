"""Shared, serializable contracts for orchestrated agents."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AgentContext(BaseModel):
    """Mutable-by-replacement state passed between independent analysis agents."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    market_data: dict[str, Any] | None = None
    technical_analysis: dict[str, Any] | None = None
    news: list[dict[str, Any]] = Field(default_factory=list)
    news_analysis: dict[str, Any] | None = None
    ai_analysis: dict[str, Any] | None = None
    memory: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    timestamps: dict[str, datetime] = Field(default_factory=dict)

    @classmethod
    def for_symbol(cls, symbol: str) -> "AgentContext":
        """Create a normalized context for a single read-only analysis request."""
        return cls(symbol=symbol.upper().strip(), timestamps={"created_at": datetime.now(timezone.utc)})


class AgentResult(BaseModel):
    """Uniform outcome returned by every replaceable agent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: Literal["success", "partial", "failed", "skipped"]
    duration_ms: float = 0.0
    messages: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    updated_context: AgentContext
