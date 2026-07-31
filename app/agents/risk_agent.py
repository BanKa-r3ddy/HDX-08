"""Portfolio-level virtual-trade approval agent."""
from __future__ import annotations

import logging

from app.services.risk_service import RiskService
from .models import AgentContext, AgentResult


class RiskAgent:
    """Evaluates portfolio risk after DecisionAgent and before PaperTradingAgent."""

    name = "Risk"
    enabled_by_default = True

    def __init__(self, risk_service: RiskService) -> None:
        self._risk_service = risk_service
        self._logger = logging.getLogger("hdx08.multi_agent.risk")

    def run(self, context: AgentContext) -> AgentResult:
        """Attach a risk report and recommended virtual capital to explicit paper actions."""
        updated = context.model_copy(deep=True)
        action = updated.metadata.get("paper_action", {})
        action_type = str(action.get("action", "NONE")).upper() if isinstance(action, dict) else "NONE"
        price = float((updated.market_data or {}).get("price", 0))
        ai = updated.ai_analysis or {}
        confidence = int(action.get("confidence", ai.get("confidence", 0)))
        indicators = (updated.technical_analysis or {}).get("indicators", {})
        atr, close = indicators.get("atr_14"), (updated.market_data or {}).get("price")
        volatility = float(atr) / float(close) if isinstance(atr, (float, int)) and isinstance(close, (float, int)) and close else 0.0
        report = self._risk_service.evaluate(updated.symbol, price, confidence, action=action_type, volatility=volatility)
        updated.metadata["risk_report"] = report.model_dump(mode="json")
        stats = self._risk_service.get_portfolio_stats()
        updated.open_positions = [trade.model_dump(mode="json") for trade in self._risk_service.get_open_positions()]
        updated.portfolio_value, updated.cash_balance, updated.daily_pnl = stats.portfolio_value, stats.cash, stats.daily_return
        if isinstance(action, dict) and report.approved:
            action["recommended_capital"] = report.recommended_capital
            updated.metadata["paper_action"] = action
        status = "success" if report.approved else "partial"
        self._logger.info("agent_risk_completed", extra={"request_id": updated.request_id, "symbol": updated.symbol, "approved": report.approved})
        return AgentResult(status=status, messages=[report.reason], errors=report.warnings, updated_context=updated)
