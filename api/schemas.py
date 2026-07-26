"""Pydantic request and response contracts."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from app.services.technical_analysis import TechnicalSummary
from app.services.gemini_service import GeminiAnalysis

class AnalyzeRequest(BaseModel):
    """A manual request for an analysis-only workflow."""
    symbol: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z.\-]+$")

class AnalyzeResponse(BaseModel):
    """Serialized workflow result."""
    symbol: str
    analysis_id: int
    workflow: dict[str, Any]
    disclaimer: str


class SymbolAnalysisResponse(BaseModel):
    """Read-only latest quote and technical summary for a market symbol."""

    symbol: str
    price: float
    analysis: TechnicalSummary


class AIAnalysisResponse(BaseModel):
    """Combined source data, technical result, and Gemini explanation."""

    symbol: str
    market_data: dict[str, Any]
    technical_analysis: dict[str, Any]
    ai_analysis: GeminiAnalysis
