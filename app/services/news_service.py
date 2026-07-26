"""Extensible, read-only news aggregation with Google News RSS as the default."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import html
import logging
import re
from time import sleep
from typing import Protocol
from urllib.parse import quote_plus
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field
import requests


class NewsArticle(BaseModel):
    """Normalized article emitted by every news provider."""

    model_config = ConfigDict(frozen=True)
    title: str
    source: str
    published_at: datetime
    url: str
    summary: str | None = None


class NewsFetchResult(BaseModel):
    """Aggregated current news and non-fatal provider failure messages."""

    model_config = ConfigDict(frozen=True)
    articles: list[NewsArticle]
    errors: list[str] = Field(default_factory=list)


class NewsProvider(Protocol):
    """Provider extension point for Google RSS, NewsAPI, Finnhub, or Polygon."""

    name: str

    def fetch(self, query: str, limit: int) -> list[NewsArticle]:
        """Return normalized articles, raising only provider-specific failures."""


class GoogleNewsRssProvider:
    """Fetches public Google News RSS search results with timeout and retry."""

    name = "google_news_rss"

    def __init__(self, session: requests.Session | None = None, timeout_seconds: float = 8.0, max_retries: int = 3) -> None:
        if timeout_seconds <= 0 or max_retries < 1:
            raise ValueError("timeout_seconds must be positive and max_retries must be at least one")
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._logger = logging.getLogger("hdx08.news.google_rss")

    def fetch(self, query: str, limit: int) -> list[NewsArticle]:
        """Request and parse the latest RSS items for a company or symbol query."""
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        response: requests.Response | None = None
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._session.get(url, timeout=self._timeout_seconds)
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                last_error = exc
                self._logger.warning("google_news_attempt_failed", extra={"query": query, "attempt": attempt, "error": str(exc)})
                if attempt < self._max_retries:
                    sleep(0.2 * attempt)
        if response is None:
            raise RuntimeError("Google News RSS is unavailable") from last_error
        return self._parse(response.content, limit)

    @staticmethod
    def _parse(content: bytes, limit: int) -> list[NewsArticle]:
        root = ElementTree.fromstring(content)
        articles: list[NewsArticle] = []
        for item in root.findall("./channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            source = (item.findtext("source") or "Google News").strip()
            raw_published = item.findtext("pubDate") or ""
            if not title or not link:
                continue
            try:
                published_at = parsedate_to_datetime(raw_published).astimezone(timezone.utc)
            except (TypeError, ValueError):
                published_at = datetime.now(timezone.utc)
            description = item.findtext("description")
            summary = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(description or ""))).strip() or None
            articles.append(NewsArticle(title=title, source=source, published_at=published_at, url=link, summary=summary))
        return articles


class NewsService:
    """Provider-agnostic news service; add a provider without changing NewsAgent."""

    def __init__(self, providers: list[NewsProvider] | None = None) -> None:
        self._providers = providers or [GoogleNewsRssProvider()]
        self._logger = logging.getLogger("hdx08.news")

    def get_news(self, symbol: str, company_name: str | None = None, limit: int = 10) -> NewsFetchResult:
        """Fetch, deduplicate, and newest-first sort at most ten relevant articles."""
        if not symbol.strip() or limit < 1:
            return NewsFetchResult(articles=[], errors=["A symbol and positive limit are required"])
        query = company_name.strip() if company_name and company_name.strip() else symbol.upper().strip()
        collected: list[NewsArticle] = []
        errors: list[str] = []
        for provider in self._providers:
            try:
                collected.extend(provider.fetch(query, limit))
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                self._logger.warning("news_provider_failed", extra={"provider": provider.name, "symbol": symbol, "error": str(exc)})
        unique: dict[tuple[str, str], NewsArticle] = {}
        for article in collected:
            key = (article.title.casefold().strip(), article.url.split("?")[0])
            unique.setdefault(key, article)
        articles = sorted(unique.values(), key=lambda article: article.published_at, reverse=True)[:limit]
        self._logger.info("news_fetched", extra={"symbol": symbol, "query": query, "articles": len(articles), "errors": len(errors)})
        return NewsFetchResult(articles=articles, errors=errors)
