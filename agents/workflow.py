"""Composable, analysis-only orchestration workflow."""
from __future__ import annotations

from typing import Any

from app.services.market_data import MarketDataService, MarketHistory
from app.services.technical_analysis import TechnicalAnalysisService
from memory.workflow_memory import WorkflowMemory
from tools.interfaces import NewsTool, StorageTool, TechnicalIndicatorTool

from .base import AnalysisAgent


class PlannerAgent(AnalysisAgent):
    """Defines the read-only analysis plan."""
    def __init__(self) -> None: super().__init__("planner")
    def run(self, memory: WorkflowMemory) -> dict[str, Any]:
        result = {"objective": "research", "stages": ["scan", "signal", "trade_plan", "risk", "decision"]}
        memory.put("plan", result); self.logger.info("Planned analysis for %s", memory.symbol); return result


class ScannerAgent(AnalysisAgent):
    """Collects a market snapshot and contextual headlines."""
    def __init__(self, market_data: MarketDataService, technical_analysis: TechnicalAnalysisService, news: NewsTool) -> None:
        super().__init__("scanner"); self._market_data = market_data; self._technical_analysis = technical_analysis; self._news = news
    def run(self, memory: WorkflowMemory) -> dict[str, Any]:
        quote = self._market_data.get_quote(memory.symbol)
        history = self._market_data.get_history(memory.symbol)
        technical_analysis: dict[str, Any]
        if isinstance(history, MarketHistory):
            technical_analysis = self._technical_analysis.analyze(history.to_dataframe()).model_dump(mode="json")
        else:
            technical_analysis = {"error": history.error, "code": history.code}
        result = {"quote": quote.model_dump(mode="json"), "technical_analysis": technical_analysis, "headlines": self._news.headlines(memory.symbol)}
        memory.put("scan", result); self.logger.info("Scanned %s", memory.symbol); return result


class SignalAgent(AnalysisAgent):
    """Generates a mocked signal from deterministic indicators."""
    def __init__(self, indicators: TechnicalIndicatorTool) -> None:
        super().__init__("signal"); self._indicators = indicators
    def run(self, memory: WorkflowMemory) -> dict[str, Any]:
        quote = memory.get("scan")["quote"]
        if "price" not in quote:
            result = {"direction": "unknown", "confidence": 0.0, "indicators": {}, "mode": "market_data_unavailable"}
            memory.put("signal", result); self.logger.warning("Signal skipped for %s due to unavailable market data", memory.symbol); return result
        price = float(quote["price"])
        indicators = self._indicators.calculate([price * 0.98, price * 0.99, price])
        result = {"direction": "neutral", "confidence": 0.5, "indicators": indicators, "mode": "mock"}
        memory.put("signal", result); self.logger.info("Generated signal for %s", memory.symbol); return result


class TradePlannerAgent(AnalysisAgent):
    """Creates a hypothetical plan, never an executable order."""
    def __init__(self) -> None: super().__init__("trade_planner")
    def run(self, memory: WorkflowMemory) -> dict[str, Any]:
        result = {"status": "hypothetical", "action": "observe", "reason": "Version 1 provides research only"}
        memory.put("trade_plan", result); self.logger.info("Created hypothetical plan for %s", memory.symbol); return result


class RiskManagerAgent(AnalysisAgent):
    """Applies conservative risk policy to a hypothetical plan."""
    def __init__(self) -> None: super().__init__("risk_manager")
    def run(self, memory: WorkflowMemory) -> dict[str, Any]:
        result = {"approved": True, "risk_level": "low", "constraints": ["No live trading", "No order execution"]}
        memory.put("risk", result); self.logger.info("Assessed risk for %s", memory.symbol); return result


class DecisionAgent(AnalysisAgent):
    """Creates the final research decision."""
    def __init__(self) -> None: super().__init__("decision")
    def run(self, memory: WorkflowMemory) -> dict[str, Any]:
        result = {"decision": "hold", "rationale": "Mocked workflow; informational output only", "executable": False}
        memory.put("decision", result); self.logger.info("Made decision for %s", memory.symbol); return result


class MonitoringAgent(AnalysisAgent):
    """Records post-workflow monitoring state."""
    def __init__(self) -> None: super().__init__("monitoring")
    def run(self, memory: WorkflowMemory) -> dict[str, Any]:
        result = {"status": "healthy", "next_action": "await next manual analysis request"}
        memory.put("monitoring", result); self.logger.info("Monitored %s", memory.symbol); return result


class AnalysisWorkflow:
    """Dependency-injected coordinator for the seven-agent research workflow."""
    def __init__(self, agents: list[AnalysisAgent], storage: StorageTool) -> None:
        self._agents, self._storage = agents, storage

    def analyze(self, symbol: str) -> dict[str, Any]:
        """Execute all agents synchronously and persist the auditable output."""
        memory = WorkflowMemory(symbol=symbol.upper())
        stages: dict[str, Any] = {}
        for agent in self._agents:
            stages[agent.name] = agent.run(memory)
        result = {"symbol": memory.symbol, "workflow": stages, "disclaimer": "Analysis only. This system does not place trades."}
        result["analysis_id"] = self._storage.save_analysis(memory.symbol, result)
        return result
