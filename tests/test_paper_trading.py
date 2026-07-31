"""Offline tests for the local-only paper-trading engine."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from app.agents.models import AgentContext
from app.agents.paper_trading_agent import PaperTradingAgent
from app.services.paper_trading_service import PaperTradingError, PaperTradingService, TradeManager
from main import build_workflow


def paper_service(tmp_path: Path) -> PaperTradingService:
    """Create an isolated virtual portfolio for each test."""
    return PaperTradingService(TradeManager(tmp_path / "paper.sqlite3"))


def test_virtual_trade_open_close_and_portfolio_pnl(tmp_path: Path) -> None:
    service = paper_service(tmp_path)
    trade = service.trade_manager.open_trade("AAPL", 1_000.0, 80, ["Test reasoning"], stop_loss=950, take_profit=1_100)
    assert trade.status == "OPEN"
    assert trade.quantity == 10  # 10% of ₹100000
    assert service.trade_manager.get_portfolio().cash_balance == 90_000.0
    closed = service.trade_manager.close_trade(trade.trade_id, 1_100.0)
    assert closed.status == "CLOSED"
    assert closed.pnl == 1_000.0
    assert closed.roi == 10.0
    assert service.trade_manager.get_portfolio().cash_balance == 101_000.0


def test_virtual_risk_rules_and_stop_loss(tmp_path: Path) -> None:
    service = paper_service(tmp_path)
    with pytest.raises(PaperTradingError, match="confidence"):
        service.trade_manager.open_trade("AAPL", 100.0, 69, ["Low confidence"])
    trades = [service.trade_manager.open_trade(f"SYM{index}", 100.0, 80, ["Allowed"]) for index in range(5)]
    with pytest.raises(PaperTradingError, match="maximum"):
        service.trade_manager.open_trade("EXTRA", 100.0, 80, ["Too many"])
    triggered = service.trade_manager.update_trade(trades[0].trade_id, 90.0)
    assert triggered.status == "OPEN"  # No stop loss was configured for this test position.
    protected = service.trade_manager.close_trade(trades[1].trade_id, 90.0, "STOP LOSS")
    assert protected.status == "STOP LOSS"


def test_paper_agent_requires_explicit_action_and_refreshes_context(tmp_path: Path) -> None:
    service = paper_service(tmp_path)
    context = AgentContext.for_symbol("AAPL")
    context.market_data = {"price": 1_000.0}
    context.ai_analysis = {"confidence": 80, "reasoning": ["Virtual test only"]}
    context.metadata["paper_action"] = {"action": "BUY", "stop_loss": 950.0, "take_profit": 1_100.0}
    result = PaperTradingAgent(service).run(context)
    assert result.status == "success"
    assert len(result.updated_context.open_positions) == 1
    assert result.updated_context.cash_balance == 90_000.0


def test_paper_trading_endpoints(tmp_path: Path) -> None:
    service = paper_service(tmp_path)
    service.trade_manager.open_trade("AAPL", 1_000.0, 80, ["Endpoint test"])
    client = TestClient(create_app(build_workflow(), paper_trading=service))
    assert client.get("/portfolio").status_code == 200
    assert len(client.get("/trades/open").json()) == 1
    assert len(client.get("/trades").json()) == 1
    reset = client.post("/paper/reset")
    assert reset.status_code == 200
    assert reset.json()["portfolio_value"] == 100_000.0
