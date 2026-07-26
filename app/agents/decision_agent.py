"""Gemini-backed market explanation agent."""
from __future__ import annotations

import logging

from app.services.gemini_service import GeminiAnalysisError, GeminiService
from .models import AgentContext, AgentResult


class DecisionAgent:
    """Produces an analysis explanation; it cannot place or recommend orders."""

    name = "Decision"
    enabled_by_default = True

    def __init__(self, gemini: GeminiService) -> None:
        self._gemini = gemini
        self._logger = logging.getLogger("hdx08.multi_agent.decision")

    def run(self, context: AgentContext) -> AgentResult:
        """Request Gemini explanation from only already-collected context data."""
        updated = context.model_copy(deep=True)
        if updated.market_data is None or updated.technical_analysis is None:
            error = "Decision analysis skipped: market or technical data is unavailable"
            updated.errors.append(error)
            return AgentResult(status="skipped", messages=[error], errors=[error], updated_context=updated)
        result = self._gemini.analyze_market({"symbol": updated.symbol, "market_data": updated.market_data,
                                              "technical_analysis": updated.technical_analysis})
        if isinstance(result, GeminiAnalysisError):
            error = f"Gemini analysis: {result.error}"
            updated.ai_analysis = result.model_dump(mode="json")
            updated.errors.append(error)
            return AgentResult(status="partial", errors=[error], updated_context=updated)
        updated.ai_analysis = result.model_dump(mode="json")
        self._logger.info("agent_decision_completed", extra={"request_id": updated.request_id, "symbol": updated.symbol})
        return AgentResult(status="success", messages=["AI market explanation completed"], updated_context=updated)
