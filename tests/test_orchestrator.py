"""Tests for the dependency-injected multi-agent architecture."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from api.app import create_app
from app.agents import DecisionAgent, MemoryAgent, PlannerAgent, ScannerAgent, TechnicalAgent
from app.orchestrator import Orchestrator
from app.services.gemini_service import GeminiAnalysis
from app.services.market_data import HistoricalBar, MarketHistory, MarketQuote
from app.services.technical_analysis import TechnicalAnalysisService
from main import build_workflow


class StubMarketData:
    """Offline data provider with enough bars for all configured indicators."""

    def get_quote(self, symbol: str) -> MarketQuote:
        return MarketQuote(symbol=symbol.upper(), price=200.0, open=199.0, high=201.0, low=198.0,
                           previous_close=198.5, volume=2_000_000, currency="USD", exchange="NMS",
                           timestamp=datetime.now(timezone.utc))

    def get_history(self, symbol: str) -> MarketHistory:
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        bars = [HistoricalBar(timestamp=start + timedelta(days=index), open=100.0 + index, high=101.0 + index,
                              low=99.0 + index, close=100.5 + index, volume=1_000_000 + (index * 1_000))
                for index in range(250)]
        return MarketHistory(symbol=symbol.upper(), period="6mo", interval="1d", bars=bars)


class StubGemini:
    """Offline Gemini double returning schema-valid analysis."""

    def analyze_market(self, _: object) -> GeminiAnalysis:
        return GeminiAnalysis(overall_sentiment="Bullish", confidence=84, market_summary="Supplied momentum is positive.",
                              strengths=["Bullish EMA alignment"], weaknesses=["Market data can change"],
                              risk_level="Medium", reasoning=["Trend is bullish", "Volume is above average"])


def build_test_orchestrator(database_path: Path) -> Orchestrator:
    """Build a fully injected orchestrator with no network dependencies."""
    market_data = StubMarketData()
    technical = TechnicalAnalysisService()
    return Orchestrator([PlannerAgent(), ScannerAgent(market_data), TechnicalAgent(technical),
                         DecisionAgent(StubGemini()), MemoryAgent(database_path)])


def test_orchestrator_runs_full_lifecycle_and_persists_memory(tmp_path: Path) -> None:
    database_path = tmp_path / "agent-memory.sqlite3"
    result = build_test_orchestrator(database_path).run("aapl", request_id="request-123")
    assert result.request_id == "request-123"
    assert result.completed_agents == ["Planner", "Scanner", "Technical", "Decision", "Memory"]
    assert result.result["market_data"]["symbol"] == "AAPL"
    assert result.result["technical_analysis"]["summary"]["trend"] == "Bullish"
    assert result.result["ai_analysis"]["confidence"] == 84
    assert result.execution_time_ms >= 0
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT request_id, symbol, confidence, trend FROM agent_memory").fetchone()
    assert row == ("request-123", "AAPL", 84, "Bullish")


def test_run_endpoint_returns_public_final_context(tmp_path: Path) -> None:
    market_data = StubMarketData()
    orchestrator = build_test_orchestrator(tmp_path / "endpoint-memory.sqlite3")
    response = TestClient(create_app(build_workflow(market_data), market_data, TechnicalAnalysisService(), StubGemini(), orchestrator)).get("/run/AAPL")
    assert response.status_code == 200
    payload = response.json()
    assert payload["completed_agents"] == ["Planner", "Scanner", "Technical", "Decision", "Memory"]
    assert payload["result"]["ai_analysis"]["overall_sentiment"] == "Bullish"
