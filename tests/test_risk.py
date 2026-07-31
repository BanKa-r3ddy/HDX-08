"""Unit tests for configurable virtual portfolio intelligence and risk gating."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from app.agents.models import AgentContext
from app.agents.risk_agent import RiskAgent
from app.models.portfolio import RiskConfig
from app.services.paper_trading_service import PaperTradingService, TradeManager
from app.services.risk_service import RiskRepository, RiskService
from main import build_workflow


def risk_service(tmp_path: Path, configuration: RiskConfig | None = None) -> tuple[RiskService, PaperTradingService]:
    """Create isolated virtual portfolio and persistence for each risk test."""
    paper = PaperTradingService(TradeManager(tmp_path / "paper.sqlite3"))
    return RiskService(paper, RiskRepository(tmp_path / "risk.sqlite3"), configuration or RiskConfig()), paper


def test_risk_approves_confidence_weighted_virtual_position_and_persists(tmp_path: Path) -> None:
    service, _ = risk_service(tmp_path)
    report = service.evaluate("AAPL", price=100.0, confidence=80, volatility=0.01)
    assert report.approved is True
    assert report.recommended_quantity == 79
    assert report.recommended_capital == 7_900.0
    assert service.latest_report() == report


def test_risk_rejects_sector_limit_and_low_confidence(tmp_path: Path) -> None:
    config = RiskConfig(max_sector_allocation=0.10)
    service, paper = risk_service(tmp_path, config)
    paper.trade_manager.open_trade("MSFT", 100.0, 80, ["Existing technology position"])
    report = service.evaluate("AAPL", price=100.0, confidence=80)
    assert report.approved is False
    assert any("sector" in warning.lower() for warning in report.warnings)
    low_confidence = service.evaluate("JPM", price=100.0, confidence=69)
    assert low_confidence.approved is False
    assert any("confidence" in warning.lower() for warning in low_confidence.warnings)


def test_risk_agent_populates_portfolio_context_without_trading(tmp_path: Path) -> None:
    service, _ = risk_service(tmp_path)
    context = AgentContext.for_symbol("AAPL")
    context.market_data = {"price": 100.0}
    context.ai_analysis = {"confidence": 80}
    context.metadata["paper_action"] = {"action": "BUY", "confidence": 80}
    result = RiskAgent(service).run(context)
    assert result.status == "success"
    assert result.updated_context.metadata["risk_report"]["approved"] is True
    assert result.updated_context.metadata["paper_action"]["recommended_capital"] > 0


def test_portfolio_risk_api_endpoints(tmp_path: Path) -> None:
    service, _ = risk_service(tmp_path)
    service.evaluate("AAPL", price=100.0, confidence=80)
    client = TestClient(create_app(build_workflow(), risk_service=service))
    assert client.get("/portfolio/risk").status_code == 200
    assert client.get("/portfolio/stats").status_code == 200
    assert client.get("/portfolio/exposure").status_code == 200
    assert client.get("/portfolio/sectors").status_code == 200
