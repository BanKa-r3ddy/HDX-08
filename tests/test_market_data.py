"""Unit tests for the provider-isolated market-data service."""
from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd
from fastapi.testclient import TestClient

from api.app import create_app
from app.services.market_data import MarketDataError, MarketDataService, MarketQuote
from main import build_workflow


class FakeTicker:
    """Deterministic yfinance test double."""
    history_metadata = {"currency": "USD", "exchangeName": "NMS"}

    def history(self, **_: object) -> pd.DataFrame:
        return pd.DataFrame(
            {"Open": [100.0, 101.0], "High": [102.0, 103.0], "Low": [99.0, 100.0],
             "Close": [101.0, 102.5], "Volume": [1_000, 2_000]},
            index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
        )


def test_get_quote_normalizes_yahoo_data_and_caches(monkeypatch) -> None:
    calls = 0
    def ticker_factory(_: str) -> FakeTicker:
        nonlocal calls
        calls += 1
        return FakeTicker()
    monkeypatch.setattr("app.services.market_data.yf.Ticker", ticker_factory)
    service = MarketDataService()
    first, second = service.get_quote("aapl"), service.get_quote("AAPL")
    assert isinstance(first, MarketQuote)
    assert first.symbol == "AAPL"
    assert first.price == 102.5
    assert first.previous_close == 101.0
    assert first.volume == 2_000
    assert second == first
    assert calls == 1


def test_get_history_returns_normalized_bars(monkeypatch) -> None:
    monkeypatch.setattr("app.services.market_data.yf.Ticker", lambda _: FakeTicker())
    result = MarketDataService().get_history("AAPL")
    assert not isinstance(result, MarketDataError)
    assert len(result.bars) == 2
    assert result.bars[-1].close == 102.5


def test_provider_failure_returns_error_without_crashing(monkeypatch) -> None:
    class BrokenTicker:
        def history(self, **_: object) -> pd.DataFrame:
            raise ConnectionError("network unavailable")
    monkeypatch.setattr("app.services.market_data.yf.Ticker", lambda _: BrokenTicker())
    result = MarketDataService(max_retries=1).get_quote("AAPL")
    assert isinstance(result, MarketDataError)
    assert result.code == "provider_unavailable"


def test_market_endpoint_returns_quote_from_injected_service() -> None:
    class StubService:
        def get_quote(self, symbol: str) -> MarketQuote:
            return MarketQuote(symbol=symbol.upper(), price=212.15, open=210.34, high=214.20, low=209.90,
                               previous_close=211.0, volume=54_832_112, currency="USD", exchange="NMS",
                               timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    response = TestClient(create_app(build_workflow(), StubService())).get("/market/AAPL")
    assert response.status_code == 200
    assert response.json()["price"] == 212.15
    assert response.json()["volume"] == 54_832_112
