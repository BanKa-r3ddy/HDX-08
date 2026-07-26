"""Workflow integration tests."""
from app.services.market_data import MarketDataError
from main import build_workflow


class UnavailableMarketData:
    """Offline service double that verifies workflow failure tolerance."""

    def get_quote(self, symbol: str) -> MarketDataError:
        return MarketDataError(symbol=symbol, code="provider_unavailable", error="offline test")

def test_workflow_is_analysis_only() -> None:
    result = build_workflow(UnavailableMarketData()).analyze("aapl")
    assert result["symbol"] == "AAPL"
    assert result["workflow"]["decision"]["executable"] is False
    assert result["analysis_id"] > 0
