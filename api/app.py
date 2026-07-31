"""FastAPI application factory."""
from __future__ import annotations
from fastapi import FastAPI, HTTPException
from agents.workflow import AnalysisWorkflow
from api.schemas import AIAnalysisResponse, AnalyzeRequest, AnalyzeResponse, FullAnalysisResponse, NewsResponse, PaperResetResponse, SymbolAnalysisResponse
from app.services.market_data import MarketDataError, MarketDataService, MarketHistory, QuoteResult
from app.services.technical_analysis import TechnicalAnalysisError, TechnicalAnalysisService
from app.services.gemini_service import GeminiAnalysisError, GeminiService
from app.orchestrator import Orchestrator, OrchestrationResult
from app.services.news_service import NewsService
from app.models.trade import PortfolioSnapshot, Trade
from app.services.paper_trading_service import PaperTradingService, TradeManager
from app.models.backtest import BacktestConfig, BacktestResult
from app.services.backtest_service import BacktestService
from app.models.portfolio import PortfolioStats, RiskConfig, RiskReport, SectorExposure
from app.services.risk_service import RiskRepository, RiskService

def create_app(workflow: AnalysisWorkflow, market_data: MarketDataService | None = None, technical_analysis: TechnicalAnalysisService | None = None, gemini: GeminiService | None = None, orchestrator: Orchestrator | None = None, news_service: NewsService | None = None, paper_trading: PaperTradingService | None = None, backtest_service: BacktestService | None = None, risk_service: RiskService | None = None) -> FastAPI:
    """Build the API with its injected analysis workflow."""
    data_service = market_data or MarketDataService()
    analysis_service = technical_analysis or TechnicalAnalysisService()
    gemini_service = gemini or GeminiService()
    news = news_service or NewsService()
    if paper_trading is None:
        from config.settings import settings
        paper_trading = PaperTradingService(TradeManager(settings.database_path))
    if risk_service is None:
        from config.settings import settings
        risk_service = RiskService(paper_trading, RiskRepository(settings.database_path.parent / "risk.sqlite3"), RiskConfig())
    agent_orchestrator = orchestrator
    app = FastAPI(title="HDX-08", version="0.1.0", description="Analysis-only AI trading platform architecture")
    @app.post("/analyze", response_model=AnalyzeResponse)
    def analyze(request: AnalyzeRequest) -> dict[str, object]:
        """Run a mocked, non-executable analysis workflow."""
        return workflow.analyze(request.symbol)
    @app.get("/market/{symbol}", response_model=QuoteResult)
    def market_quote(symbol: str) -> QuoteResult:
        """Return a cached, read-only Yahoo Finance market quote."""
        return data_service.get_quote(symbol)
    @app.get("/analyze/{symbol}", response_model=SymbolAnalysisResponse | MarketDataError | TechnicalAnalysisError)
    def analyze_symbol(symbol: str) -> SymbolAnalysisResponse | MarketDataError | TechnicalAnalysisError:
        """Return read-only quote data and technical analysis for a symbol."""
        quote = data_service.get_quote(symbol)
        if isinstance(quote, MarketDataError):
            return quote
        history = data_service.get_history(symbol)
        if isinstance(history, MarketDataError):
            return history
        analysis = analysis_service.analyze(history.to_dataframe())
        if isinstance(analysis, TechnicalAnalysisError):
            return analysis
        return SymbolAnalysisResponse(symbol=quote.symbol, price=quote.price, analysis=analysis.summary)
    @app.get("/ai-analysis/{symbol}", response_model=AIAnalysisResponse | MarketDataError | TechnicalAnalysisError | GeminiAnalysisError)
    def ai_analysis(symbol: str) -> AIAnalysisResponse | MarketDataError | TechnicalAnalysisError | GeminiAnalysisError:
        """Return source data, technical analysis, and a non-executing Gemini explanation."""
        quote = data_service.get_quote(symbol)
        if isinstance(quote, MarketDataError):
            return quote
        history = data_service.get_history(symbol)
        if isinstance(history, MarketDataError):
            return history
        technical = analysis_service.analyze(history.to_dataframe())
        if isinstance(technical, TechnicalAnalysisError):
            return technical
        generated = gemini_service.analyze_market({"symbol": quote.symbol, "market_data": quote.model_dump(mode="json"),
                                                   "technical_analysis": technical.model_dump(mode="json")})
        if isinstance(generated, GeminiAnalysisError):
            return generated
        return AIAnalysisResponse(symbol=quote.symbol, market_data=quote.model_dump(mode="json"),
                                  technical_analysis=technical.model_dump(mode="json"), ai_analysis=generated)
    @app.get("/run/{symbol}", response_model=OrchestrationResult)
    def run_agents(symbol: str) -> OrchestrationResult:
        """Run the dependency-injected Planner→Scanner→Technical→Decision→Memory lifecycle."""
        if agent_orchestrator is None:
            from app.agents import DecisionAgent, MemoryAgent, NewsAgent, PlannerAgent, ScannerAgent, TechnicalAgent
            from config.settings import settings
            local_orchestrator = Orchestrator([PlannerAgent(), ScannerAgent(data_service), TechnicalAgent(analysis_service),
                                              NewsAgent(news, gemini_service), DecisionAgent(gemini_service), MemoryAgent(settings.database_path)])
            return local_orchestrator.run(symbol)
        return agent_orchestrator.run(symbol)
    @app.get("/news/{symbol}", response_model=NewsResponse)
    def news_for_symbol(symbol: str, company_name: str | None = None) -> NewsResponse:
        """Fetch current Google News RSS articles and a strict Gemini news summary."""
        fetched = news.get_news(symbol, company_name=company_name)
        analysis = gemini_service.analyze_news({"symbol": symbol.upper(), "news": [article.model_dump(mode="json") for article in fetched.articles]})
        return NewsResponse(symbol=symbol.upper(), news=fetched.articles, news_analysis=analysis.model_dump(mode="json"))
    @app.get("/full-analysis/{symbol}", response_model=FullAnalysisResponse)
    def full_analysis(symbol: str) -> FullAnalysisResponse:
        """Run the complete non-executing multi-agent market and news pipeline."""
        run = run_agents(symbol)
        return FullAnalysisResponse(request_id=run.request_id, symbol=run.symbol, market_data=run.result["market_data"],
                                    technical_analysis=run.result["technical_analysis"], news=run.result["news"],
                                    news_analysis=run.result["news_analysis"], ai_analysis=run.result["ai_analysis"], errors=run.errors)
    @app.get("/portfolio", response_model=PortfolioSnapshot)
    def portfolio() -> PortfolioSnapshot:
        """Return virtual-paper portfolio balances and open positions."""
        return paper_trading.trade_manager.get_portfolio()
    @app.get("/trades", response_model=list[Trade])
    def trades() -> list[Trade]:
        """Return complete virtual trade history."""
        return paper_trading.trade_manager.get_trade_history()
    @app.get("/trades/open", response_model=list[Trade])
    def open_trades() -> list[Trade]:
        """Return only currently open virtual positions."""
        return paper_trading.trade_manager.get_open_positions()
    @app.post("/paper/reset", response_model=PaperResetResponse)
    def reset_paper_portfolio() -> PaperResetResponse:
        """Reset virtual paper balance and delete virtual trade history."""
        snapshot = paper_trading.trade_manager.reset()
        return PaperResetResponse(message="Virtual paper portfolio reset", portfolio_value=snapshot.portfolio_value)
    @app.get("/portfolio/risk", response_model=RiskReport)
    def portfolio_risk() -> RiskReport:
        """Return the latest virtual portfolio risk report."""
        return risk_service.latest_report()
    @app.get("/portfolio/stats", response_model=PortfolioStats)
    def portfolio_stats() -> PortfolioStats:
        """Return virtual portfolio performance and risk statistics."""
        return risk_service.get_portfolio_stats()
    @app.get("/portfolio/exposure", response_model=list[SectorExposure])
    def portfolio_exposure() -> list[SectorExposure]:
        """Return current sector-classified virtual exposure."""
        return risk_service.get_sector_exposure()
    @app.get("/portfolio/sectors", response_model=list[SectorExposure])
    def portfolio_sectors() -> list[SectorExposure]:
        """Return current sector allocation; alias for /portfolio/exposure."""
        return risk_service.get_sector_exposure()
    @app.get("/backtest", response_model=list[BacktestResult])
    def backtest_index() -> list[BacktestResult]:
        """List completed historical replays (compatibility alias for /backtests)."""
        return _backtests().list()
    @app.post("/backtest/run", response_model=BacktestResult)
    def run_backtest(configuration: BacktestConfig) -> BacktestResult:
        """Replay daily historical data through the isolated multi-agent backtest pipeline."""
        return _backtests().run(configuration)
    @app.get("/backtest/{backtest_id}", response_model=BacktestResult)
    def get_backtest(backtest_id: str) -> BacktestResult:
        """Return one persisted completed backtest."""
        result = _backtests().get(backtest_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Backtest was not found")
        return result
    @app.get("/backtests", response_model=list[BacktestResult])
    def backtests() -> list[BacktestResult]:
        """List completed backtests newest first."""
        return _backtests().list()

    def _backtests() -> BacktestService:
        """Build lazily only for direct app-factory callers that omit DI wiring."""
        if backtest_service is not None:
            return backtest_service
        from main import build_backtest_service
        return build_backtest_service(data_service, analysis_service, gemini_service, news)
    return app
