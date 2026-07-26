"""FastAPI application factory."""
from __future__ import annotations
from fastapi import FastAPI
from agents.workflow import AnalysisWorkflow
from api.schemas import AnalyzeRequest, AnalyzeResponse

def create_app(workflow: AnalysisWorkflow) -> FastAPI:
    """Build the API with its injected analysis workflow."""
    app = FastAPI(title="HDX-08", version="0.1.0", description="Analysis-only AI trading platform architecture")
    @app.post("/analyze", response_model=AnalyzeResponse)
    def analyze(request: AnalyzeRequest) -> dict[str, object]:
        """Run a mocked, non-executable analysis workflow."""
        return workflow.analyze(request.symbol)
    return app
