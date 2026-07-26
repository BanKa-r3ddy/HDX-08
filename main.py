"""HDX-08 application entry point."""
from __future__ import annotations

import uvicorn
from rich.console import Console

from agents.workflow import (AnalysisWorkflow, DecisionAgent, MonitoringAgent, PlannerAgent,
    RiskManagerAgent, ScannerAgent, SignalAgent, TradePlannerAgent)
from app.services.market_data import MarketDataService
from app.services.technical_analysis import TechnicalAnalysisService
from api.app import create_app
from config.logging import configure_logging
from config.settings import settings
from database.sqlite_storage import SQLiteStorage
from tools.interfaces import MockNews, SimpleIndicators


def build_workflow(market_data: MarketDataService | None = None, technical_analysis: TechnicalAnalysisService | None = None) -> AnalysisWorkflow:
    """Compose production boundaries with safe local adapters for Version 1."""
    agents = [PlannerAgent(), ScannerAgent(market_data or MarketDataService(), technical_analysis or TechnicalAnalysisService(), MockNews()), SignalAgent(SimpleIndicators()),
              TradePlannerAgent(), RiskManagerAgent(), DecisionAgent(), MonitoringAgent()]
    return AnalysisWorkflow(agents, SQLiteStorage(settings.database_path))


def main() -> None:
    """Start the local development API server."""
    configure_logging(settings.log_level)
    Console().print("[bold green]HDX-08[/bold green] analysis-only API starting on http://127.0.0.1:8000")
    market_data = MarketDataService()
    technical_analysis = TechnicalAnalysisService()
    workflow = build_workflow(market_data, technical_analysis)
    uvicorn.run(create_app(workflow, market_data, technical_analysis), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
