"""Read-only technical-analysis service for normalized OHLCV data."""
from __future__ import annotations

import logging
from typing import Literal, TypeAlias

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, SMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import VolumeWeightedAveragePrice


class SupportResistance(BaseModel):
    """Most recent confirmed local support and resistance levels."""

    support: float | None
    resistance: float | None


class TechnicalSummary(BaseModel):
    """Compact technical state intended for API and agent consumers."""

    trend: Literal["Bullish", "Bearish", "Sideways"]
    rsi: float | None
    macd: Literal["Bullish", "Bearish", "Neutral"]
    volume: Literal["Above Average", "Below Average", "Average", "Unavailable"]
    strength: Literal["Weak", "Moderate", "Strong"]
    support: float | None
    resistance: float | None


class TechnicalAnalysisResult(BaseModel):
    """Technical summary plus latest values for every supported indicator."""

    model_config = ConfigDict(frozen=True)
    summary: TechnicalSummary
    indicators: dict[str, float | None]


class TechnicalAnalysisError(BaseModel):
    """Safe analysis failure returned for invalid or insufficient input data."""

    model_config = ConfigDict(frozen=True)
    error: str
    code: Literal["invalid_data", "analysis_error"]


TechnicalAnalysisResponse: TypeAlias = TechnicalAnalysisResult | TechnicalAnalysisError


class TechnicalAnalysisService:
    """Computes standard indicators over a pandas OHLCV DataFrame.

    Input columns may use either Yahoo-style title case (``Close``) or canonical
    lower case (``close``). Calculations are read-only and never issue orders.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger("hdx08.technical_analysis")

    def analyze(self, market_data: pd.DataFrame) -> TechnicalAnalysisResponse:
        """Calculate indicators and a compact latest-bar technical summary."""
        try:
            indicators = self.calculate_indicators(market_data)
            result = TechnicalAnalysisResult(summary=self.summary(indicators), indicators=self._latest_indicators(indicators))
            self._logger.info("technical_analysis_completed", extra={"rows": len(indicators)})
            return result
        except ValueError as exc:
            self._logger.warning("technical_analysis_invalid_data", extra={"error": str(exc)})
            return TechnicalAnalysisError(code="invalid_data", error=str(exc))
        except Exception as exc:
            self._logger.exception("technical_analysis_failed", extra={"error": str(exc)})
            return TechnicalAnalysisError(code="analysis_error", error="Technical analysis could not be calculated")

    def calculate_indicators(self, market_data: pd.DataFrame) -> pd.DataFrame:
        """Return a copied frame enriched with SMA, EMA, RSI, MACD, BB, ATR, VWAP, and volume SMA."""
        frame = self._normalize_frame(market_data)
        close, high, low, volume = frame["close"], frame["high"], frame["low"], frame["volume"]
        for window in (20, 50, 200):
            frame[f"sma_{window}"] = SMAIndicator(close, window=window, fillna=False).sma_indicator()
        for window in (9, 21, 50):
            frame[f"ema_{window}"] = EMAIndicator(close, window=window, fillna=False).ema_indicator()
        frame["rsi_14"] = RSIIndicator(close, window=14, fillna=False).rsi()
        macd = MACD(close, window_slow=26, window_fast=12, window_sign=9, fillna=False)
        frame["macd"] = macd.macd()
        frame["macd_signal"] = macd.macd_signal()
        frame["macd_histogram"] = macd.macd_diff()
        bands = BollingerBands(close, window=20, window_dev=2, fillna=False)
        frame["bb_upper"] = bands.bollinger_hband()
        frame["bb_middle"] = bands.bollinger_mavg()
        frame["bb_lower"] = bands.bollinger_lband()
        frame["atr_14"] = AverageTrueRange(high, low, close, window=14, fillna=False).average_true_range()
        frame["vwap"] = VolumeWeightedAveragePrice(high, low, close, volume, window=14, fillna=False).volume_weighted_average_price()
        frame["volume_sma_20"] = volume.rolling(window=20, min_periods=20).mean()
        return frame

    def get_trend(self, indicators: pd.DataFrame) -> Literal["Bullish", "Bearish", "Sideways"]:
        """Classify trend from 9/21/50 EMA alignment."""
        latest = indicators.iloc[-1]
        values = [latest["ema_9"], latest["ema_21"], latest["ema_50"]]
        if any(pd.isna(value) for value in values):
            return "Sideways"
        if latest["ema_9"] > latest["ema_21"] > latest["ema_50"]:
            return "Bullish"
        if latest["ema_9"] < latest["ema_21"] < latest["ema_50"]:
            return "Bearish"
        return "Sideways"

    def market_strength(self, indicators: pd.DataFrame) -> Literal["Weak", "Moderate", "Strong"]:
        """Classify strength from relative volume, ATR percentage, and EMA momentum."""
        latest = indicators.iloc[-1]
        required = ("volume_sma_20", "atr_14", "close", "ema_21")
        if any(pd.isna(latest[column]) for column in required) or latest["close"] == 0:
            return "Weak"
        volume_score = latest["volume"] > latest["volume_sma_20"]
        atr_score = (latest["atr_14"] / latest["close"]) >= 0.01
        momentum_score = abs(latest["close"] - latest["ema_21"]) / latest["close"] >= 0.01
        score = sum((volume_score, atr_score, momentum_score))
        return "Strong" if score == 3 else "Moderate" if score >= 1 else "Weak"

    def support_resistance(self, indicators: pd.DataFrame) -> SupportResistance:
        """Locate the latest two-bar-confirmed swing low and swing high."""
        highs, lows = indicators["high"], indicators["low"]
        swing_high = (highs > highs.shift(1)) & (highs > highs.shift(-1)) & (highs > highs.shift(2)) & (highs > highs.shift(-2))
        swing_low = (lows < lows.shift(1)) & (lows < lows.shift(-1)) & (lows < lows.shift(2)) & (lows < lows.shift(-2))
        resistance = highs[swing_high].iloc[-1] if swing_high.any() else highs.tail(20).max()
        support = lows[swing_low].iloc[-1] if swing_low.any() else lows.tail(20).min()
        return SupportResistance(support=self._number(support), resistance=self._number(resistance))

    def summary(self, indicators: pd.DataFrame) -> TechnicalSummary:
        """Build the requested compact technical-analysis summary."""
        latest = indicators.iloc[-1]
        macd_value, signal_value = latest["macd"], latest["macd_signal"]
        macd: Literal["Bullish", "Bearish", "Neutral"] = "Neutral" if pd.isna(macd_value) or pd.isna(signal_value) else ("Bullish" if macd_value > signal_value else "Bearish" if macd_value < signal_value else "Neutral")
        volume: Literal["Above Average", "Below Average", "Average", "Unavailable"]
        if pd.isna(latest["volume_sma_20"]):
            volume = "Unavailable"
        elif latest["volume"] > latest["volume_sma_20"] * 1.02:
            volume = "Above Average"
        elif latest["volume"] < latest["volume_sma_20"] * 0.98:
            volume = "Below Average"
        else:
            volume = "Average"
        levels = self.support_resistance(indicators)
        return TechnicalSummary(trend=self.get_trend(indicators), rsi=self._number(latest["rsi_14"]), macd=macd,
                                volume=volume, strength=self.market_strength(indicators), support=levels.support, resistance=levels.resistance)

    def _normalize_frame(self, market_data: pd.DataFrame) -> pd.DataFrame:
        if market_data.empty:
            raise ValueError("Market data is empty")
        renamed = market_data.rename(columns={column: str(column).lower().replace(" ", "_") for column in market_data.columns}).copy()
        required = {"open", "high", "low", "close", "volume"}
        missing = required.difference(renamed.columns)
        if missing:
            raise ValueError(f"Market data is missing required columns: {', '.join(sorted(missing))}")
        for column in required:
            renamed[column] = pd.to_numeric(renamed[column], errors="coerce")
        if renamed[list(required)].isna().any().any():
            raise ValueError("Market data contains non-numeric OHLCV values")
        return renamed.sort_index()

    def _latest_indicators(self, indicators: pd.DataFrame) -> dict[str, float | None]:
        columns = ("sma_20", "sma_50", "sma_200", "ema_9", "ema_21", "ema_50", "rsi_14", "macd", "macd_signal", "macd_histogram", "bb_upper", "bb_middle", "bb_lower", "atr_14", "vwap", "volume_sma_20")
        latest = indicators.iloc[-1]
        return {column: self._number(latest[column]) for column in columns}

    @staticmethod
    def _number(value: object) -> float | None:
        numeric = float(value)
        return None if np.isnan(numeric) or np.isinf(numeric) else round(numeric, 4)
