"""FastAPI application factory."""
from __future__ import annotations
from fastapi import FastAPI
from agents.workflow import AnalysisWorkflow
from api.schemas import AIAnalysisResponse, AnalyzeRequest, AnalyzeResponse, SymbolAnalysisResponse
from app.services.market_data import MarketDataError, MarketDataService, MarketHistory, QuoteResult
from app.services.technical_analysis import TechnicalAnalysisError, TechnicalAnalysisService
from app.services.gemini_service import GeminiAnalysisError, GeminiService
from app.orchestrator import Orchestrator, OrchestrationResult

def create_app(workflow: AnalysisWorkflow, market_data: MarketDataService | None = None, technical_analysis: TechnicalAnalysisService | None = None, gemini: GeminiService | None = None, orchestrator: Orchestrator | None = None) -> FastAPI:
    """Build the API with its injected analysis workflow."""
    data_service = market_data or MarketDataService()
    analysis_service = technical_analysis or TechnicalAnalysisService()
    gemini_service = gemini or GeminiService()
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
            from app.agents import DecisionAgent, MemoryAgent, PlannerAgent, ScannerAgent, TechnicalAgent
            from config.settings import settings
            local_orchestrator = Orchestrator([PlannerAgent(), ScannerAgent(data_service), TechnicalAgent(analysis_service),
                                              DecisionAgent(gemini_service), MemoryAgent(settings.database_path)])
            return local_orchestrator.run(symbol)
        return agent_orchestrator.run(symbol)
    return app
