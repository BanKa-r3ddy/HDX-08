"""FastAPI application factory."""
from __future__ import annotations
from fastapi import FastAPI
from agents.workflow import AnalysisWorkflow
from api.schemas import AnalyzeRequest, AnalyzeResponse, SymbolAnalysisResponse
from app.services.market_data import MarketDataError, MarketDataService, MarketHistory, QuoteResult
from app.services.technical_analysis import TechnicalAnalysisError, TechnicalAnalysisService

def create_app(workflow: AnalysisWorkflow, market_data: MarketDataService | None = None, technical_analysis: TechnicalAnalysisService | None = None) -> FastAPI:
    """Build the API with its injected analysis workflow."""
    data_service = market_data or MarketDataService()
    analysis_service = technical_analysis or TechnicalAnalysisService()
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
    return app
