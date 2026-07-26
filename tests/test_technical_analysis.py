"""Unit tests for the technical-analysis engine."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from api.app import create_app
from app.services.market_data import HistoricalBar, MarketHistory, MarketQuote
from app.services.technical_analysis import TechnicalAnalysisError, TechnicalAnalysisService
from main import build_workflow


def price_frame(rows: int = 250) -> pd.DataFrame:
    """Create deterministic rising OHLCV data sufficient for all lookbacks."""
    index = pd.date_range("2025-01-01", periods=rows, freq="D", tz="UTC")
    close = np.linspace(100.0, 180.0, rows)
    return pd.DataFrame({"Open": close - 0.5, "High": close + 1.0, "Low": close - 1.0,
                         "Close": close, "Volume": np.linspace(1_000_000, 2_000_000, rows)}, index=index)


def test_calculates_all_requested_indicators_and_bullish_summary() -> None:
    service = TechnicalAnalysisService()
    result = service.analyze(price_frame())
    assert not isinstance(result, TechnicalAnalysisError)
    assert result.summary.trend == "Bullish"
    assert result.summary.rsi is not None
    assert result.summary.macd == "Bullish"
    assert result.indicators["sma_200"] is not None
    assert result.indicators["vwap"] is not None
    assert result.indicators["volume_sma_20"] is not None


def test_invalid_frame_returns_safe_error() -> None:
    result = TechnicalAnalysisService().analyze(pd.DataFrame({"close": [1.0]}))
    assert isinstance(result, TechnicalAnalysisError)
    assert result.code == "invalid_data"


def test_analyze_endpoint_returns_compact_technical_summary() -> None:
    frame = price_frame()
    bars = [HistoricalBar(timestamp=index.to_pydatetime(), open=float(row.Open), high=float(row.High),
                          low=float(row.Low), close=float(row.Close), volume=int(row.Volume))
            for index, row in frame.iterrows()]

    class StubMarketData:
        def get_quote(self, symbol: str) -> MarketQuote:
            return MarketQuote(symbol=symbol, price=180.0, open=179.5, high=181.0, low=179.0,
                               previous_close=179.7, volume=2_000_000, currency="USD", exchange="NMS",
                               timestamp=datetime.now(timezone.utc))

        def get_history(self, symbol: str) -> MarketHistory:
            return MarketHistory(symbol=symbol, period="6mo", interval="1d", bars=bars)

    market_data = StubMarketData()
    response = TestClient(create_app(build_workflow(market_data), market_data, TechnicalAnalysisService())).get("/analyze/AAPL")
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "AAPL"
    assert payload["price"] == 180.0
    assert payload["analysis"]["trend"] == "Bullish"
