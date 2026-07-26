"""Offline tests for Gemini structured-analysis integration."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.app import create_app
from app.services.gemini_service import GeminiAnalysis, GeminiAnalysisError, GeminiService, MarketAnalysisInput, SYSTEM_INSTRUCTION
from app.services.market_data import HistoricalBar, MarketHistory, MarketQuote
from app.services.technical_analysis import TechnicalAnalysisService
from main import build_workflow


class FakeResponse:
    """Minimal SDK response double."""
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed


class RetryingClient:
    """Fails once, then returns schema-valid structured content."""
    def __init__(self) -> None:
        self.calls = 0
        self.config = None

    def generate_content(self, **kwargs: object) -> FakeResponse:
        self.calls += 1
        self.config = kwargs["config"]
        if self.calls == 1:
            raise TimeoutError("transient provider timeout")
        return FakeResponse({"overall_sentiment": "Bullish", "confidence": 84,
                             "market_summary": "The supplied indicators show positive momentum.",
                             "strengths": ["Price is above EMA 21"], "weaknesses": ["Volatility remains elevated"],
                             "risk_level": "Medium", "reasoning": ["EMA alignment is bullish", "MACD is positive"]})


def payload() -> dict[str, object]:
    return {"symbol": "AAPL", "market_data": {"price": 212.15}, "technical_analysis": {"summary": {"trend": "Bullish"}}}


def test_gemini_service_retries_and_validates_structured_response() -> None:
    client = RetryingClient()
    result = GeminiService(api_key="test", max_retries=2, client=client).analyze_market(payload())
    assert isinstance(result, GeminiAnalysis)
    assert result.confidence == 84
    assert client.calls == 2
    assert client.config.temperature == 0.2
    assert client.config.system_instruction == SYSTEM_INSTRUCTION


def test_gemini_service_returns_safe_error_without_api_key() -> None:
    result = GeminiService(api_key=None).analyze_market(payload())
    assert isinstance(result, GeminiAnalysisError)
    assert result.code == "api_key_missing"


def test_ai_analysis_endpoint_combines_pipeline_data() -> None:
    bars = [HistoricalBar(timestamp=datetime(2025, 1, index + 1, tzinfo=timezone.utc), open=100 + index,
                          high=101 + index, low=99 + index, close=100.5 + index, volume=1_000_000 + index)
            for index in range(31)]

    class StubMarketData:
        def get_quote(self, symbol: str) -> MarketQuote:
            return MarketQuote(symbol=symbol, price=130.5, open=130.0, high=131.0, low=129.0,
                               previous_close=129.5, volume=1_000_030, currency="USD", exchange="NMS",
                               timestamp=datetime.now(timezone.utc))
        def get_history(self, symbol: str) -> MarketHistory:
            return MarketHistory(symbol=symbol, period="6mo", interval="1d", bars=bars)

    class StubGemini:
        def analyze_market(self, _: object) -> GeminiAnalysis:
            return GeminiAnalysis(overall_sentiment="Neutral", confidence=50, market_summary="Insufficient Data",
                                  strengths=[], weaknesses=[], risk_level="Insufficient Data", reasoning=["Insufficient Data"])

    market_data = StubMarketData()
    response = TestClient(create_app(build_workflow(market_data, TechnicalAnalysisService(), StubGemini()), market_data,
                                     TechnicalAnalysisService(), StubGemini())).get("/ai-analysis/AAPL")
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "AAPL"
    assert body["market_data"]["price"] == 130.5
    assert body["ai_analysis"]["overall_sentiment"] == "Neutral"
