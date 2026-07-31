"""ASGI application module for ``uvicorn app.main:app``."""
from __future__ import annotations

from api.app import create_app
from app.services.market_data import MarketDataService
from app.services.technical_analysis import TechnicalAnalysisService
from app.services.gemini_service import GeminiService
from app.services.news_service import NewsService
from main import build_backtest_service, build_orchestrator, build_paper_trading_service, build_risk_service, build_workflow


# A single injected service instance is shared by the HTTP endpoint and scanner,
# so 60-second quote caching applies consistently across both code paths.
market_data_service = MarketDataService()
technical_analysis_service = TechnicalAnalysisService()
gemini_service = GeminiService()
news_service = NewsService()
paper_trading_service = build_paper_trading_service()
risk_service = build_risk_service(paper_trading_service)
backtest_service = build_backtest_service(market_data_service, technical_analysis_service, gemini_service, news_service)
orchestrator = build_orchestrator(market_data_service, technical_analysis_service, gemini_service, news_service, paper_trading_service, risk_service)
app = create_app(build_workflow(market_data_service, technical_analysis_service, gemini_service), market_data_service, technical_analysis_service, gemini_service, orchestrator, news_service, paper_trading_service, backtest_service, risk_service)
