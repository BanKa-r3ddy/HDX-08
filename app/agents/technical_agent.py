"""Technical-analysis execution agent."""
from __future__ import annotations

import logging

import pandas as pd

from app.services.technical_analysis import TechnicalAnalysisError, TechnicalAnalysisService
from .models import AgentContext, AgentResult


class TechnicalAgent:
    """Calculates technical analysis from ScannerAgent's normalized history."""

    name = "Technical"
    enabled_by_default = True

    def __init__(self, technical_analysis: TechnicalAnalysisService) -> None:
        self._technical_analysis = technical_analysis
        self._logger = logging.getLogger("hdx08.multi_agent.technical")

    def run(self, context: AgentContext) -> AgentResult:
        """Calculate indicators when historical data is available."""
        updated = context.model_copy(deep=True)
        frame = updated.metadata.get("history_frame")
        if not isinstance(frame, pd.DataFrame):
            error = "Technical analysis skipped: historical market data is unavailable"
            updated.errors.append(error)
            return AgentResult(status="skipped", messages=[error], errors=[error], updated_context=updated)
        result = self._technical_analysis.analyze(frame)
        if isinstance(result, TechnicalAnalysisError):
            error = f"Technical analysis: {result.error}"
            updated.errors.append(error)
            return AgentResult(status="failed", errors=[error], updated_context=updated)
        updated.technical_analysis = result.model_dump(mode="json")
        self._logger.info("agent_technical_completed", extra={"request_id": updated.request_id, "symbol": updated.symbol})
        return AgentResult(status="success", messages=["Technical analysis completed"], updated_context=updated)
