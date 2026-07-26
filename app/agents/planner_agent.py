"""Rule-based execution planning agent."""
from __future__ import annotations

import logging

from .models import AgentContext, AgentResult


class PlannerAgent:
    """Chooses enabled downstream agents using simple, non-AI rules."""

    name = "Planner"
    enabled_by_default = True

    def __init__(self) -> None:
        self._logger = logging.getLogger("hdx08.multi_agent.planner")

    def run(self, context: AgentContext) -> AgentResult:
        """Plan all agents advertised as enabled by the injected orchestrator."""
        updated = context.model_copy(deep=True)
        available = updated.metadata.get("available_agents", [])
        planned = [name for name in available if name != self.name]
        updated.metadata["planned_agents"] = planned
        self._logger.info("agent_plan_created", extra={"request_id": updated.request_id, "symbol": updated.symbol, "planned_agents": planned})
        return AgentResult(status="success", messages=[f"Planned {len(planned)} downstream agents"], updated_context=updated)
