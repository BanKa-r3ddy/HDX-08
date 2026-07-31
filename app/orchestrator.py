"""Dependency-injected, fault-tolerant multi-agent orchestration."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from time import perf_counter
from typing import Sequence

from pydantic import BaseModel, ConfigDict

from app.agents.models import AgentContext, AgentResult
from app.agents.protocols import AnalysisAgent


class OrchestrationResult(BaseModel):
    """Public result for a complete, non-executing multi-agent run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    request_id: str
    symbol: str
    completed_agents: list[str]
    execution_time_ms: float
    result: dict[str, object]
    errors: list[str]


class Orchestrator:
    """Runs injected agents in Planner-defined order and safely collects failures."""

    def __init__(self, agents: Sequence[AnalysisAgent]) -> None:
        self._agents = {agent.name: agent for agent in agents}
        if len(self._agents) != len(agents):
            raise ValueError("Agent names must be unique")
        if "Planner" not in self._agents:
            raise ValueError("A Planner agent is required")
        self._logger = logging.getLogger("hdx08.orchestrator")

    def run(self, symbol: str, request_id: str | None = None) -> OrchestrationResult:
        """Create context, execute planned agents, and return the final public state."""
        context = AgentContext.for_symbol(symbol)
        if request_id:
            context.request_id = request_id
        enabled = [agent.name for agent in self._agents.values() if agent.enabled_by_default]
        context.metadata["available_agents"] = enabled
        started = perf_counter()
        agent_results: list[AgentResult] = []
        planner_result = self._execute(self._agents["Planner"], context)
        context = planner_result.updated_context
        agent_results.append(planner_result)
        planned = context.metadata.get("planned_agents", [name for name in enabled if name != "Planner"])
        for name in planned:
            agent = self._agents.get(name)
            if agent is None:
                error = f"Planned agent '{name}' is not registered"
                context.errors.append(error)
                continue
            result = self._execute(agent, context)
            context = result.updated_context
            agent_results.append(result)
        elapsed = round((perf_counter() - started) * 1000, 2)
        completed = [self._agent_name_for_result(result, index) for index, result in enumerate(agent_results)]
        self._logger.info("orchestration_completed", extra={"request_id": context.request_id, "symbol": context.symbol, "duration_ms": elapsed, "errors": len(context.errors)})
        return OrchestrationResult(request_id=context.request_id, symbol=context.symbol, completed_agents=completed,
                                   execution_time_ms=elapsed,
                                   result={"market_data": context.market_data or {}, "technical_analysis": context.technical_analysis or {},
                                           "news": context.news, "news_analysis": context.news_analysis or {},
                                           "ai_analysis": context.ai_analysis or {}}, errors=context.errors)

    def _execute(self, agent: AnalysisAgent, context: AgentContext) -> AgentResult:
        started = perf_counter()
        self._logger.info("agent_started", extra={"request_id": context.request_id, "agent": agent.name, "symbol": context.symbol})
        try:
            result = agent.run(context)
        except Exception as exc:  # Plug-in agents must not bring down the entire workflow.
            updated = context.model_copy(deep=True)
            error = f"{agent.name}: unexpected failure: {exc}"
            updated.errors.append(error)
            result = AgentResult(status="failed", errors=[error], updated_context=updated)
            self._logger.exception("agent_unexpected_failure", extra={"request_id": context.request_id, "agent": agent.name})
        duration = round((perf_counter() - started) * 1000, 2)
        result = result.model_copy(update={"duration_ms": duration})
        result.updated_context.timestamps[agent.name] = datetime.now(timezone.utc)
        result.updated_context.metadata.setdefault("completed_agent_names", []).append(agent.name)
        self._logger.info("agent_completed", extra={"request_id": result.updated_context.request_id, "agent": agent.name,
                                                      "status": result.status, "duration_ms": duration, "errors": len(result.errors)})
        return result

    @staticmethod
    def _agent_name_for_result(result: AgentResult, index: int) -> str:
        """Read the recorded name while retaining a safe fallback for custom agents."""
        names = result.updated_context.metadata.get("completed_agent_names", [])
        return names[index] if index < len(names) else f"Agent-{index + 1}"
