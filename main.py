"""HDX-08 application entry point."""
from __future__ import annotations

import uvicorn
from rich.console import Console

from agents.workflow import (AnalysisWorkflow, DecisionAgent, MonitoringAgent, PlannerAgent,
    RiskManagerAgent, ScannerAgent, SignalAgent, TradePlannerAgent)
from app.services.market_data import MarketDataService
from app.services.technical_analysis import TechnicalAnalysisService
from app.services.gemini_service import GeminiService
from app.services.news_service import NewsService
from app.services.paper_trading_service import PaperTradingService, TradeManager
from app.services.backtest_service import BacktestRepository, BacktestService, YFinanceHistoricalDataProvider
from app.services.risk_service import RiskRepository, RiskService
from app.models.portfolio import RiskConfig
from app.agents import BacktestAgent, DecisionAgent as MultiAgentDecisionAgent, MemoryAgent, NewsAgent, PaperTradingAgent, PlannerAgent as MultiAgentPlannerAgent, RiskAgent, ScannerAgent as MultiAgentScannerAgent, TechnicalAgent
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
                       gemini: GeminiService | None = None, news_service: NewsService | None = None, paper_trading: PaperTradingService | None = None,
                       risk_service: RiskService | None = None) -> Orchestrator:
    """Compose the dependency-injected multi-agent architecture."""
    data_service = market_data or MarketDataService()
    technical_service = technical_analysis or TechnicalAnalysisService()
    gemini_service = gemini or GeminiService()
    current_news_service = news_service or NewsService()
    current_paper_trading = paper_trading or build_paper_trading_service()
    current_risk_service = risk_service or build_risk_service(current_paper_trading)
    return Orchestrator([MultiAgentPlannerAgent(), MultiAgentScannerAgent(data_service), TechnicalAgent(technical_service),
                         NewsAgent(current_news_service, gemini_service), MultiAgentDecisionAgent(gemini_service), RiskAgent(current_risk_service),
                         PaperTradingAgent(current_paper_trading), MemoryAgent(settings.database_path)])


def build_paper_trading_service() -> PaperTradingService:
    """Compose the local-only virtual trading service over the application SQLite database."""
    return PaperTradingService(TradeManager(settings.database_path))


def build_risk_service(paper_trading: PaperTradingService | None = None) -> RiskService:
    """Compose configurable portfolio intelligence over the local virtual portfolio."""
    return RiskService(paper_trading or build_paper_trading_service(), RiskRepository(settings.database_path.parent / "risk.sqlite3"), RiskConfig())


def build_backtest_service(market_data: MarketDataService | None = None, technical_analysis: TechnicalAnalysisService | None = None,
                           gemini: GeminiService | None = None, news_service: NewsService | None = None) -> BacktestService:
    """Compose an isolated historical replay pipeline without affecting live paper balances."""
    technical_service = technical_analysis or TechnicalAnalysisService()
    gemini_service = gemini or GeminiService()
    news = news_service or NewsService()
    backtest_paper = PaperTradingService(TradeManager(settings.database_path.parent / "backtest_paper.sqlite3"))
    replay_agent = BacktestAgent(MultiAgentPlannerAgent(), TechnicalAgent(technical_service), MultiAgentDecisionAgent(gemini_service),
                                 PaperTradingAgent(backtest_paper, enabled=True), MemoryAgent(settings.database_path), backtest_paper,
                                 NewsAgent(news, gemini_service))
    return BacktestService(YFinanceHistoricalDataProvider(), BacktestRepository(settings.database_path.parent / "backtests.sqlite3"), replay_agent)


def main() -> None:
    """Start the local development API server."""
    configure_logging(settings.log_level)
    Console().print("[bold green]HDX-08[/bold green] analysis-only API starting on http://127.0.0.1:8000")
    market_data = MarketDataService()
    technical_analysis = TechnicalAnalysisService()
    gemini = GeminiService()
    news_service = NewsService()
    paper_trading = build_paper_trading_service()
    risk_service = build_risk_service(paper_trading)
    backtesting = build_backtest_service(market_data, technical_analysis, gemini, news_service)
    workflow = build_workflow(market_data, technical_analysis, gemini)
    orchestrator = build_orchestrator(market_data, technical_analysis, gemini, news_service, paper_trading, risk_service)
    uvicorn.run(create_app(workflow, market_data, technical_analysis, gemini, orchestrator, news_service, paper_trading, backtesting, risk_service), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
