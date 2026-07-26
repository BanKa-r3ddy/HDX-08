"""FastAPI application factory."""
from __future__ import annotations
from fastapi import FastAPI
from agents.workflow import AnalysisWorkflow
from api.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.market_data import MarketDataService, QuoteResult

def create_app(workflow: AnalysisWorkflow, market_data: MarketDataService | None = None) -> FastAPI:
    """Build the API with its injected analysis workflow."""
    data_service = market_data or MarketDataService()
    app = FastAPI(title="HDX-08", version="0.1.0", description="Analysis-only AI trading platform architecture")
    @app.post("/analyze", response_model=AnalyzeResponse)
    def analyze(request: AnalyzeRequest) -> dict[str, object]:
        """Run a mocked, non-executable analysis workflow."""
        return workflow.analyze(request.symbol)
    @app.get("/market/{symbol}", response_model=QuoteResult)
    def market_quote(symbol: str) -> QuoteResult:
        """Return a cached, read-only Yahoo Finance market quote."""
        return data_service.get_quote(symbol)
    return app
