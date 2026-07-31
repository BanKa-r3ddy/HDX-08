"""Offline tests for Google-News-compatible aggregation and NewsAgent."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.app import create_app
from app.agents.models import AgentContext
from app.agents.news_agent import NewsAgent
from app.services.gemini_service import NewsAnalysis
from app.services.news_service import GoogleNewsRssProvider, NewsArticle, NewsService
from main import build_workflow


class StubProvider:
    """Provider double validating provider-independent aggregation."""

    name = "stub"

    def fetch(self, query: str, limit: int) -> list[NewsArticle]:
        now = datetime.now(timezone.utc)
        return [
            NewsArticle(title="Older article", source="Wire", published_at=now - timedelta(hours=2), url="https://example.com/old", summary=None),
            NewsArticle(title="Latest article", source="Wire", published_at=now, url="https://example.com/latest?tracking=1", summary="Latest"),
            NewsArticle(title="Latest article", source="Wire", published_at=now - timedelta(minutes=1), url="https://example.com/latest?tracking=2", summary="Duplicate"),
        ]


class StubGemini:
    """News-only Gemini double."""

    def analyze_news(self, _: object) -> NewsAnalysis:
        return NewsAnalysis(overall_sentiment="Bullish", confidence=83, summary="Supplied articles are positive.",
                            positive_events=["Positive article"], negative_events=[], watch_items=["Watch follow-up"])


def test_news_service_deduplicates_and_sorts_newest_first() -> None:
    result = NewsService(providers=[StubProvider()]).get_news("AAPL")
    assert len(result.articles) == 2
    assert result.articles[0].title == "Latest article"
    assert result.articles[0].summary == "Latest"


def test_google_news_rss_parser_normalizes_required_article_fields() -> None:
    xml = b"""<rss><channel><item><title>Test headline</title><link>https://example.com/story</link>
    <source>Example Source</source><pubDate>Wed, 30 Jul 2026 12:00:00 GMT</pubDate>
    <description>&lt;b&gt;A short summary&lt;/b&gt;</description></item></channel></rss>"""
    article = GoogleNewsRssProvider._parse(xml, limit=10)[0]
    assert article.title == "Test headline"
    assert article.source == "Example Source"
    assert article.url == "https://example.com/story"
    assert article.summary == "A short summary"
    assert article.published_at.tzinfo is not None


def test_news_agent_populates_context_and_analysis() -> None:
    result = NewsAgent(NewsService(providers=[StubProvider()]), StubGemini()).run(AgentContext.for_symbol("AAPL"))
    assert result.status == "success"
    assert len(result.updated_context.news) == 2
    assert result.updated_context.news_analysis is not None
    assert result.updated_context.news_analysis["confidence"] == 83


def test_news_endpoint_returns_articles_and_structured_analysis() -> None:
    service = NewsService(providers=[StubProvider()])
    response = TestClient(create_app(build_workflow(), gemini=StubGemini(), news_service=service)).get("/news/AAPL")
    assert response.status_code == 200
    assert len(response.json()["news"]) == 2
    assert response.json()["news_analysis"]["overall_sentiment"] == "Bullish"
