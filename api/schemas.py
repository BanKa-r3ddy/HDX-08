"""Pydantic request and response contracts."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field

class AnalyzeRequest(BaseModel):
    """A manual request for an analysis-only workflow."""
    symbol: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z.\-]+$")

class AnalyzeResponse(BaseModel):
    """Serialized workflow result."""
    symbol: str
    analysis_id: int
    workflow: dict[str, Any]
    disclaimer: str
