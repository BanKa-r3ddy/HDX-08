"""Market-data collection agent."""
from __future__ import annotations

import logging

from app.services.market_data import MarketDataError, MarketDataService, MarketHistory
from .models import AgentContext, AgentResult


class ScannerAgent:
    """Collects quote and OHLCV history using the injected read-only service."""

    name = "Scanner"
    enabled_by_default = True

    def __init__(self, market_data: MarketDataService) -> None:
        self._market_data = market_data
        self._logger = logging.getLogger("hdx08.multi_agent.scanner")

    def run(self, context: AgentContext) -> AgentResult:
        """Store market quote and private-to-pipeline historical DataFrame."""
        updated = context.model_copy(deep=True)
        quote, history = self._market_data.get_quote(updated.symbol), self._market_data.get_history(updated.symbol)
        errors: list[str] = []
        if isinstance(quote, MarketDataError):
            errors.append(f"Scanner quote: {quote.error}")
        else:
            updated.market_data = quote.model_dump(mode="json")
        if isinstance(history, MarketDataError):
            errors.append(f"Scanner history: {history.error}")
        elif isinstance(history, MarketHistory):
            updated.metadata["history_frame"] = history.to_dataframe()
        updated.errors.extend(errors)
        status = "success" if not errors else "partial" if updated.market_data else "failed"
        self._logger.info("agent_scan_completed", extra={"request_id": updated.request_id, "symbol": updated.symbol, "status": status, "errors": len(errors)})
        return AgentResult(status=status, messages=["Market-data scan completed"], errors=errors, updated_context=updated)
