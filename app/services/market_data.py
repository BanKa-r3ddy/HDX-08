"""Resilient, read-only Yahoo Finance market-data service."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from threading import RLock
from time import sleep
from typing import Literal, TypeAlias

from cachetools import TTLCache
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
import yfinance as yf


class MarketQuote(BaseModel):
    """Normalized latest quote returned from Yahoo Finance."""

    model_config = ConfigDict(frozen=True)
    symbol: str
    price: float
    open: float
    high: float
    low: float
    previous_close: float
    volume: int
    currency: str | None = None
    exchange: str | None = None
    timestamp: datetime


class HistoricalBar(BaseModel):
    """One normalized OHLCV observation."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketHistory(BaseModel):
    """Historical observations for one symbol."""

    model_config = ConfigDict(frozen=True)
    symbol: str
    period: str
    interval: str
    bars: list[HistoricalBar]

    def to_dataframe(self) -> pd.DataFrame:
        """Convert normalized bars back to canonical lower-case OHLCV data."""
        return pd.DataFrame([bar.model_dump() for bar in self.bars]).set_index("timestamp")


class MarketDataError(BaseModel):
    """Safe, client-facing failure result; expected provider errors are never raised."""

    model_config = ConfigDict(frozen=True)
    symbol: str
    error: str
    code: Literal["invalid_symbol", "provider_unavailable", "provider_error"]


QuoteResult: TypeAlias = MarketQuote | MarketDataError
HistoryResult: TypeAlias = MarketHistory | MarketDataError


class MarketDataService:
    """Fetches Yahoo Finance data with retry, timeout, and 60-second caching.

    This service is intentionally read-only. Provider failures are represented by
    :class:`MarketDataError`, allowing API and agent callers to degrade safely.
    """

    def __init__(self, request_timeout: float = 8.0, max_retries: int = 3, cache_ttl_seconds: int = 60) -> None:
        if request_timeout <= 0 or max_retries < 1 or cache_ttl_seconds <= 0:
            raise ValueError("timeout, retries, and cache TTL must be positive")
        self._request_timeout = request_timeout
        self._max_retries = max_retries
        self._quotes: TTLCache[str, MarketQuote] = TTLCache(maxsize=512, ttl=cache_ttl_seconds)
        self._histories: TTLCache[tuple[str, str, str], MarketHistory] = TTLCache(maxsize=256, ttl=cache_ttl_seconds)
        self._cache_lock = RLock()
        self._logger = logging.getLogger("hdx08.market_data")

    def get_quote(self, symbol: str) -> QuoteResult:
        """Return a normalized quote, or a meaningful provider error result."""
        normalized = self._normalize_symbol(symbol)
        if isinstance(normalized, MarketDataError):
            return normalized
        with self._cache_lock:
            cached = self._quotes.get(normalized)
        if cached:
            self._logger.info("market_quote_cache_hit", extra={"symbol": normalized})
            return cached
        try:
            frame, ticker = self._history_with_retry(normalized, period="5d", interval="1d")
            quote = self._quote_from_frame(normalized, frame, ticker)
        except ValueError as exc:
            return self._error(normalized, "invalid_symbol", str(exc))
        except Exception as exc:  # Provider implementations can raise varied transport errors.
            return self._error(normalized, "provider_unavailable", "Yahoo Finance is currently unavailable", exc)
        with self._cache_lock:
            self._quotes[normalized] = quote
        return quote

    def get_history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> HistoryResult:
        """Return normalized OHLCV history, or a meaningful provider error result."""
        normalized = self._normalize_symbol(symbol)
        if isinstance(normalized, MarketDataError):
            return normalized
        key = (normalized, period, interval)
        with self._cache_lock:
            cached = self._histories.get(key)
        if cached:
            self._logger.info("market_history_cache_hit", extra={"symbol": normalized})
            return cached
        try:
            frame, _ = self._history_with_retry(normalized, period=period, interval=interval)
            bars = [self._bar_from_row(index, row) for index, row in frame.iterrows()]
            history = MarketHistory(symbol=normalized, period=period, interval=interval, bars=bars)
        except ValueError as exc:
            return self._error(normalized, "invalid_symbol", str(exc))
        except Exception as exc:
            return self._error(normalized, "provider_unavailable", "Yahoo Finance is currently unavailable", exc)
        with self._cache_lock:
            self._histories[key] = history
        return history

    def get_multiple_quotes(self, list_of_symbols: list[str]) -> dict[str, QuoteResult]:
        """Fetch quotes independently so one failure cannot affect other symbols."""
        return {symbol.upper().strip(): self.get_quote(symbol) for symbol in list_of_symbols}

    def _history_with_retry(self, symbol: str, period: str, interval: str) -> tuple[pd.DataFrame, yf.Ticker]:
        last_error: Exception | None = None
        ticker = yf.Ticker(symbol)
        for attempt in range(1, self._max_retries + 1):
            try:
                frame = ticker.history(period=period, interval=interval, timeout=self._request_timeout)
                if frame.empty:
                    raise ValueError("No market data was found for this symbol")
                self._logger.info("market_data_fetched", extra={"symbol": symbol, "attempt": attempt})
                return frame, ticker
            except ValueError:
                raise
            except Exception as exc:
                last_error = exc
                self._logger.warning("market_data_attempt_failed", extra={"symbol": symbol, "attempt": attempt, "error": str(exc)})
                if attempt < self._max_retries:
                    sleep(0.2 * attempt)
        raise RuntimeError("Market data request failed after retries") from last_error

    def _quote_from_frame(self, symbol: str, frame: pd.DataFrame, ticker: yf.Ticker) -> MarketQuote:
        latest = frame.iloc[-1]
        previous = frame.iloc[-2] if len(frame) > 1 else latest
        metadata = getattr(ticker, "history_metadata", {}) or {}
        return MarketQuote(
            symbol=symbol,
            price=float(latest["Close"]), open=float(latest["Open"]), high=float(latest["High"]),
            low=float(latest["Low"]), previous_close=float(previous["Close"]), volume=int(latest["Volume"]),
            currency=metadata.get("currency"), exchange=metadata.get("exchangeName"),
            timestamp=self._as_datetime(frame.index[-1]),
        )

    def _bar_from_row(self, timestamp: object, row: pd.Series) -> HistoricalBar:
        return HistoricalBar(timestamp=self._as_datetime(timestamp), open=float(row["Open"]), high=float(row["High"]),
                             low=float(row["Low"]), close=float(row["Close"]), volume=int(row["Volume"]))

    @staticmethod
    def _as_datetime(value: object) -> datetime:
        timestamp = pd.Timestamp(value).to_pydatetime()
        return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp

    @staticmethod
    def _normalize_symbol(symbol: str) -> str | MarketDataError:
        normalized = symbol.upper().strip()
        if not normalized or len(normalized) > 20 or not all(char.isalnum() or char in ".-^=" for char in normalized):
            return MarketDataError(symbol=normalized or symbol, code="invalid_symbol", error="A valid market symbol is required")
        return normalized

    def _error(self, symbol: str, code: Literal["invalid_symbol", "provider_unavailable", "provider_error"], message: str, exception: Exception | None = None) -> MarketDataError:
        self._logger.error("market_data_error", extra={"symbol": symbol, "code": code, "error": str(exception) if exception else message})
        return MarketDataError(symbol=symbol, code=code, error=message)
