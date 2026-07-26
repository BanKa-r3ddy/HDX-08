"""HDX-08 application entry point."""
from __future__ import annotations

import uvicorn
from rich.console import Console

from agents.workflow import (AnalysisWorkflow, DecisionAgent, MonitoringAgent, PlannerAgent,
    RiskManagerAgent, ScannerAgent, SignalAgent, TradePlannerAgent)
from app.services.market_data import MarketDataService
from app.services.technical_analysis import TechnicalAnalysisService
from app.services.gemini_service import GeminiService
from app.agents import DecisionAgent as MultiAgentDecisionAgent, MemoryAgent, PlannerAgent as MultiAgentPlannerAgent, ScannerAgent as MultiAgentScannerAgent, TechnicalAgent
from app.orchestrator import Orchestrator
from api.app import create_app
from config.logging import configure_logging
from config.settings import settings
from database.sqlite_storage import SQLiteStorage
from tools.interfaces import MockNews, SimpleIndicators


def build_workflow(market_data: MarketDataService | None = None, technical_analysis: TechnicalAnalysisService | None = None, gemini: GeminiService | None = None) -> AnalysisWorkflow:
    """Compose production boundaries with safe local adapters for Version 1."""
    agents = [PlannerAgent(), ScannerAgent(market_data or MarketDataService(), technical_analysis or TechnicalAnalysisService(), MockNews()), SignalAgent(SimpleIndicators()),
              TradePlannerAgent(), RiskManagerAgent(), DecisionAgent(gemini or GeminiService()), MonitoringAgent()]
    return AnalysisWorkflow(agents, SQLiteStorage(settings.database_path))


def build_orchestrator(market_data: MarketDataService | None = None, technical_analysis: TechnicalAnalysisService | None = None,
                       gemini: GeminiService | None = None) -> Orchestrator:
    """Compose the dependency-injected multi-agent architecture."""
    data_service = market_data or MarketDataService()
    technical_service = technical_analysis or TechnicalAnalysisService()
    gemini_service = gemini or GeminiService()
    return Orchestrator([MultiAgentPlannerAgent(), MultiAgentScannerAgent(data_service), TechnicalAgent(technical_service),
                         MultiAgentDecisionAgent(gemini_service), MemoryAgent(settings.database_path)])


def main() -> None:
    """Start the local development API server."""
    configure_logging(settings.log_level)
    Console().print("[bold green]HDX-08[/bold green] analysis-only API starting on http://127.0.0.1:8000")
    market_data = MarketDataService()
    technical_analysis = TechnicalAnalysisService()
    gemini = GeminiService()
    workflow = build_workflow(market_data, technical_analysis, gemini)
    orchestrator = build_orchestrator(market_data, technical_analysis, gemini)
    uvicorn.run(create_app(workflow, market_data, technical_analysis, gemini, orchestrator), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
