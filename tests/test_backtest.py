"""Deterministic tests for multi-agent historical replay backtesting."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from api.app import create_app
from app.agents import DecisionAgent, MemoryAgent, PaperTradingAgent, PlannerAgent, TechnicalAgent
from app.agents.backtest_agent import BacktestAgent
from app.models.backtest import BacktestConfig, EquityPoint
from app.models.trade import Trade
from app.services.backtest_service import BacktestRepository, BacktestService, calculate_metrics
from app.services.gemini_service import GeminiAnalysis
from app.services.paper_trading_service import PaperTradingService, TradeManager
from app.services.technical_analysis import TechnicalAnalysisService
from main import build_workflow


class FakeHistoryProvider:
    """Network-free historical provider for daily replay tests."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def get_history(self, symbol: str, start_date: str, end_date: str, interval: str = "1d") -> pd.DataFrame:
        return self.frame.copy()


class StubGemini:
    """Valid structured decision explanation without a remote Gemini request."""

    def analyze_market(self, _: object) -> GeminiAnalysis:
        return GeminiAnalysis(overall_sentiment="Bullish", confidence=80, market_summary="Backtest context.",
                              strengths=["Trend"], weaknesses=["Risk"], risk_level="Medium", reasoning=["Historical replay"])


def replay_frame(rows: int = 260) -> pd.DataFrame:
    """Generate oscillating upward prices that create entries and exits."""
    index = pd.date_range("2020-01-01", periods=rows, freq="D", tz="UTC")
    close = 100 + (np.arange(rows) * 0.25) + (5 * np.sin(np.arange(rows) / 6))
    return pd.DataFrame({"Open": close - 0.4, "High": close + 1.0, "Low": close - 1.0,
                         "Close": close, "Volume": 1_000_000 + (np.arange(rows) * 1_000)}, index=index)


def build_backtest_service(tmp_path: Path) -> BacktestService:
    """Compose existing agents around isolated fake historical data."""
    paper = PaperTradingService(TradeManager(tmp_path / "paper.sqlite3"))
    agent = BacktestAgent(PlannerAgent(), TechnicalAgent(TechnicalAnalysisService()), DecisionAgent(StubGemini()),
                          PaperTradingAgent(paper, enabled=True), MemoryAgent(tmp_path / "memory.sqlite3"), paper)
    return BacktestService(FakeHistoryProvider(replay_frame()), BacktestRepository(tmp_path / "backtests.sqlite3"), agent)


def test_historical_replay_generates_equity_and_persists_result(tmp_path: Path) -> None:
    service = build_backtest_service(tmp_path)
    config = BacktestConfig(symbol="AAPL", start_date=date(2020, 1, 1), end_date=date(2020, 12, 31), initial_capital=100_000)
    result = service.run(config)
    assert result.equity_curve
    assert result.performance_metrics.final_portfolio_value > 0
    assert service.get(result.backtest_id) == result
    assert any(trade.status == "CLOSED" for trade in result.trade_history)


def test_metrics_calculate_roi_drawdown_and_trade_statistics() -> None:
    now = datetime.now(timezone.utc)
    win = Trade(trade_id="win", symbol="AAPL", entry_price=100, quantity=10, entry_time=now, confidence=80, reasoning=[], status="CLOSED",
                exit_price=110, exit_time=now + timedelta(days=1), pnl=100, roi=10, holding_time_seconds=86_400)
    loss = Trade(trade_id="loss", symbol="AAPL", entry_price=100, quantity=10, entry_time=now, confidence=80, reasoning=[], status="CLOSED",
                 exit_price=90, exit_time=now + timedelta(days=1), pnl=-100, roi=-10, holding_time_seconds=86_400)
    curve = [EquityPoint(date=date(2020, 1, 1), portfolio_value=100_000, cash=100_000, open_positions=0, daily_return=0),
             EquityPoint(date=date(2020, 1, 2), portfolio_value=110_000, cash=110_000, open_positions=0, daily_return=10),
             EquityPoint(date=date(2020, 1, 3), portfolio_value=99_000, cash=99_000, open_positions=0, daily_return=-10)]
    metrics = calculate_metrics(100_000, [win, loss], curve)
    assert metrics.total_trades == 2
    assert metrics.win_rate_pct == 50.0
    assert metrics.roi_pct == -1.0
    assert metrics.maximum_drawdown_pct == 10.0
    assert metrics.profit_factor == 1.0


def test_backtest_api_endpoints(tmp_path: Path) -> None:
    service = build_backtest_service(tmp_path)
    client = TestClient(create_app(build_workflow(), backtest_service=service))
    response = client.post("/backtest/run", json={"symbol": "AAPL", "start_date": "2020-01-01", "end_date": "2020-12-31", "initial_capital": 100000})
    assert response.status_code == 200
    backtest_id = response.json()["backtest_id"]
    assert client.get(f"/backtest/{backtest_id}").status_code == 200
    assert len(client.get("/backtests").json()) == 1
    assert len(client.get("/backtest").json()) == 1
