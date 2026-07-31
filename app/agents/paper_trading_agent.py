"""Optional agent that applies explicit virtual paper-trading actions only."""
from __future__ import annotations

import logging
from typing import Any

from app.services.paper_trading_service import PaperTradingError, PaperTradingService
from .models import AgentContext, AgentResult


class PaperTradingAgent:
    """Maintains a virtual portfolio; it never creates broker or real orders.

    An action must be explicitly supplied in ``context.metadata['paper_action']``.
    This preserves the analysis pipeline's non-trading default behavior.
    """

    name = "PaperTrading"
    enabled_by_default = False

    def __init__(self, paper_trading: PaperTradingService, enabled: bool = False) -> None:
        self._paper_trading = paper_trading
        self.enabled_by_default = enabled
        self._logger = logging.getLogger("hdx08.multi_agent.paper_trading")

    def run(self, context: AgentContext) -> AgentResult:
        """Apply an explicit virtual BUY/SELL action, then refresh portfolio state."""
        updated = context.model_copy(deep=True)
        action = updated.metadata.get("paper_action")
        closed_trades: list[dict[str, Any]] = []
        try:
            if isinstance(action, dict):
                action_type = str(action.get("action", "")).upper()
                price = float((updated.market_data or {}).get("price", 0))
                risk_report = updated.metadata.get("risk_report")
                if action_type == "BUY" and isinstance(risk_report, dict) and not risk_report.get("approved", False):
                    message = "Virtual paper trade rejected by RiskAgent"
                    snapshot = self._paper_trading.trade_manager.get_portfolio()
                    updated.open_positions = [trade.model_dump(mode="json") for trade in snapshot.open_positions]
                    updated.portfolio_value, updated.cash_balance, updated.daily_pnl = snapshot.portfolio_value, snapshot.cash_balance, snapshot.daily_pnl
                    return AgentResult(status="skipped", messages=[message], errors=list(risk_report.get("warnings", [])), updated_context=updated)
                if action_type == "BUY":
                    ai = updated.ai_analysis or {}
                    confidence = int(action.get("confidence", ai.get("confidence", 0)))
                    reasoning = action.get("reasoning", ai.get("reasoning", [ai.get("market_summary", "Insufficient Data")]))
                    trade = self._paper_trading.trade_manager.open_trade(updated.symbol, price, confidence, list(reasoning),
                                                                         action.get("stop_loss"), action.get("take_profit"), action.get("recommended_capital"))
                    message = f"Opened virtual trade {trade.trade_id}"
                elif action_type == "SELL":
                    trade = self._paper_trading.trade_manager.close_trade(str(action["trade_id"]), price)
                    closed_trades.append(trade.model_dump(mode="json"))
                    message = f"Closed virtual trade {trade.trade_id}"
                else:
                    message = "No virtual paper-trading action requested"
            else:
                message = "No virtual paper-trading action requested"
            snapshot = self._paper_trading.trade_manager.get_portfolio()
            updated.open_positions = [trade.model_dump(mode="json") for trade in snapshot.open_positions]
            updated.portfolio_value, updated.cash_balance, updated.daily_pnl = snapshot.portfolio_value, snapshot.cash_balance, snapshot.daily_pnl
            if closed_trades:
                updated.metadata["completed_trades"] = closed_trades
            status = "success" if isinstance(action, dict) else "skipped"
            self._logger.info("paper_trading_agent_completed", extra={"request_id": updated.request_id, "symbol": updated.symbol, "status": status})
            return AgentResult(status=status, messages=[message], updated_context=updated)
        except (PaperTradingError, KeyError, TypeError, ValueError) as exc:
            error = f"Paper trading: {exc}"
            updated.errors.append(error)
            return AgentResult(status="failed", errors=[error], updated_context=updated)
