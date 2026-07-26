"""Protocol interfaces for infrastructure concerns."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Protocol


class MarketDataTool(Protocol):
    """Provides read-only market snapshots."""
    def quote(self, symbol: str) -> dict[str, Any]: ...


class TechnicalIndicatorTool(Protocol):
    """Calculates technical indicators from price observations."""
    def calculate(self, prices: list[float]) -> dict[str, float]: ...


class NewsTool(Protocol):
    """Retrieves relevant market news without trading side effects."""
    def headlines(self, symbol: str) -> list[str]: ...


class NotificationTool(Protocol):
    """Publishes informational notifications."""
    def notify(self, message: str) -> None: ...


class LoggingTool(Protocol):
    """Records workflow events."""
    def event(self, message: str) -> None: ...


class StorageTool(Protocol):
    """Persists workflow records."""
    def save_analysis(self, symbol: str, payload: dict[str, Any]) -> int: ...


class MockMarketData:
    """Deterministic local market-data adapter for development."""
    def quote(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol.upper(), "price": 100.0, "as_of": datetime.now(timezone.utc).isoformat()}


class SimpleIndicators:
    """Small dependency-free indicator implementation."""
    def calculate(self, prices: list[float]) -> dict[str, float]:
        if not prices:
            raise ValueError("prices must not be empty")
        average = sum(prices) / len(prices)
        return {"sma": round(average, 2), "momentum": round(prices[-1] - prices[0], 2)}


class MockNews:
    """Safe local news adapter."""
    def headlines(self, symbol: str) -> list[str]:
        return [f"Mock market context for {symbol.upper()}: no live news requested."]


class StandardLogger:
    """Logging adapter implementing the logging tool contract."""
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def event(self, message: str) -> None:
        self._logger.info(message)


class NullNotifier:
    """Notification adapter that logs rather than sends external messages."""
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def notify(self, message: str) -> None:
        self._logger.info("Notification: %s", message)
