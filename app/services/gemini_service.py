"""Safe Gemini integration for analysis explanation, never trade execution."""
from __future__ import annotations

import json
import logging
import os
from time import sleep
from typing import Any, Literal, Protocol, TypeAlias

from google import genai
from google.genai import types
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

load_dotenv()


SYSTEM_INSTRUCTION = """You are an analysis-only market research assistant.
Reason exclusively from the supplied JSON input. Never use outside knowledge,
assume facts, invent values, or claim to have accessed any other data source.
If a required conclusion cannot be supported by supplied fields, write exactly
'Insufficient Data' for that conclusion. Do not provide buy/sell/hold advice,
orders, position sizes, price targets, or execution instructions. Return only
the JSON object required by the response schema."""


class MarketAnalysisInput(BaseModel):
    """Data boundary passed to Gemini; no external context is supplied."""

    symbol: str
    market_data: dict[str, Any]
    technical_analysis: dict[str, Any]
    news_analysis: dict[str, Any] | None = None


class NewsAnalysisInput(BaseModel):
    """News-only data boundary passed to Gemini."""

    symbol: str
    news: list[dict[str, Any]]


class GeminiAnalysis(BaseModel):
    """Validated structured explanation returned by Gemini."""

    model_config = ConfigDict(frozen=True)
    overall_sentiment: Literal["Bullish", "Bearish", "Neutral", "Insufficient Data"]
    confidence: int = Field(ge=0, le=100)
    market_summary: str
    strengths: list[str]
    weaknesses: list[str]
    risk_level: Literal["Low", "Medium", "High", "Insufficient Data"]
    reasoning: list[str]


class GeminiAnalysisError(BaseModel):
    """Safe response for unavailable credentials, provider, or validation failures."""

    model_config = ConfigDict(frozen=True)
    error: str
    code: Literal["api_key_missing", "provider_unavailable", "invalid_model_response", "invalid_input"]


GeminiResult: TypeAlias = GeminiAnalysis | GeminiAnalysisError


class NewsAnalysis(BaseModel):
    """Validated sentiment explanation based exclusively on supplied articles."""

    model_config = ConfigDict(frozen=True)
    overall_sentiment: Literal["Bullish", "Bearish", "Neutral", "Insufficient Data"]
    confidence: int = Field(ge=0, le=100)
    summary: str
    positive_events: list[str]
    negative_events: list[str]
    watch_items: list[str]


class NewsAnalysisError(BaseModel):
    """Safe error returned when news analysis cannot be generated."""

    model_config = ConfigDict(frozen=True)
    error: str
    code: Literal["api_key_missing", "provider_unavailable", "invalid_model_response", "invalid_input"]


NewsGeminiResult: TypeAlias = NewsAnalysis | NewsAnalysisError


class ContentGenerator(Protocol):
    """Small SDK seam used to test the service without network access."""

    def generate_content(self, *, model: str, contents: str, config: types.GenerateContentConfig) -> Any:
        """Generate a structured model response."""


class GeminiService:
    """Calls Gemini with strict structured output, retry, timeout, and safe failures."""

    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-flash", timeout_seconds: float = 15.0,
                 max_retries: int = 3, client: ContentGenerator | None = None) -> None:
        if timeout_seconds <= 0 or max_retries < 1:
            raise ValueError("timeout_seconds must be positive and max_retries must be at least one")
        self._api_key = api_key if api_key is not None else os.getenv("GOOGLE_API_KEY")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._client = client
        self._logger = logging.getLogger("hdx08.gemini")

    def analyze_market(self, payload: MarketAnalysisInput | dict[str, Any]) -> GeminiResult:
        """Explain supplied market and technical JSON, returning only validated structure."""
        try:
            request = payload if isinstance(payload, MarketAnalysisInput) else MarketAnalysisInput.model_validate(payload)
        except ValidationError as exc:
            self._logger.warning("gemini_invalid_input", extra={"error": str(exc)})
            return GeminiAnalysisError(code="invalid_input", error="Market-analysis input is invalid")
        if self._client is None and not self._api_key:
            self._logger.warning("gemini_api_key_missing")
            return GeminiAnalysisError(code="api_key_missing", error="GOOGLE_API_KEY is not configured")
        try:
            response = self._generate_with_retry(request)
            parsed = getattr(response, "parsed", None)
            raw = parsed if parsed is not None else json.loads(response.text)
            result = GeminiAnalysis.model_validate(raw)
            self._logger.info("gemini_analysis_completed", extra={"symbol": request.symbol})
            return result
        except ValidationError as exc:
            self._logger.error("gemini_invalid_response", extra={"symbol": request.symbol, "error": str(exc)})
            return GeminiAnalysisError(code="invalid_model_response", error="Gemini returned an invalid analysis response")
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            self._logger.error("gemini_non_json_response", extra={"symbol": request.symbol, "error": str(exc)})
            return GeminiAnalysisError(code="invalid_model_response", error="Gemini did not return valid JSON")
        except Exception as exc:
            self._logger.error("gemini_provider_unavailable", extra={"symbol": request.symbol, "error": str(exc)})
            return GeminiAnalysisError(code="provider_unavailable", error="Gemini is currently unavailable")

    def analyze_news(self, payload: NewsAnalysisInput | dict[str, Any]) -> NewsGeminiResult:
        """Return structured article-grounded sentiment without using external context."""
        try:
            request = payload if isinstance(payload, NewsAnalysisInput) else NewsAnalysisInput.model_validate(payload)
        except ValidationError as exc:
            self._logger.warning("gemini_news_invalid_input", extra={"error": str(exc)})
            return NewsAnalysisError(code="invalid_input", error="News-analysis input is invalid")
        if self._client is None and not self._api_key:
            return NewsAnalysisError(code="api_key_missing", error="GOOGLE_API_KEY is not configured")
        instruction = SYSTEM_INSTRUCTION + "\nFor news analysis, base every event only on the supplied article list."
        try:
            response = self._generate_structured(request, NewsAnalysis, instruction)
            raw = getattr(response, "parsed", None)
            result = NewsAnalysis.model_validate(raw if raw is not None else json.loads(response.text))
            self._logger.info("gemini_news_completed", extra={"symbol": request.symbol, "articles": len(request.news)})
            return result
        except ValidationError as exc:
            self._logger.error("gemini_news_invalid_response", extra={"symbol": request.symbol, "error": str(exc)})
            return NewsAnalysisError(code="invalid_model_response", error="Gemini returned an invalid news analysis response")
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            return NewsAnalysisError(code="invalid_model_response", error="Gemini did not return valid JSON news analysis")
        except Exception as exc:
            self._logger.error("gemini_news_unavailable", extra={"symbol": request.symbol, "error": str(exc)})
            return NewsAnalysisError(code="provider_unavailable", error="Gemini is currently unavailable")

    def _generate_with_retry(self, request: MarketAnalysisInput) -> Any:
        return self._generate_structured(request, GeminiAnalysis, SYSTEM_INSTRUCTION)

    def _generate_structured(self, request: MarketAnalysisInput | NewsAnalysisInput, response_schema: type[BaseModel], instruction: str) -> Any:
        client = self._client or genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=int(self._timeout_seconds * 1000)),
        ).models
        config = types.GenerateContentConfig(
            system_instruction=instruction,
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        content = json.dumps(request.model_dump(mode="json"), separators=(",", ":"))
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                return client.generate_content(model=self._model, contents=content, config=config)
            except Exception as exc:
                last_error = exc
                self._logger.warning("gemini_attempt_failed", extra={"symbol": request.symbol, "attempt": attempt, "error": str(exc)})
                if attempt < self._max_retries:
                    sleep(0.25 * attempt)
        raise RuntimeError("Gemini request failed after retries") from last_error
