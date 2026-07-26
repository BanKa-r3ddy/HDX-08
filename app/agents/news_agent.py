"""News collection and article-grounded sentiment agent."""
from __future__ import annotations

import logging

from app.services.gemini_service import GeminiService, NewsAnalysisError
from app.services.news_service import NewsService
from .models import AgentContext, AgentResult


class NewsAgent:
    """Fetches current news through a provider-agnostic service and analyzes it."""

    name = "News"
    enabled_by_default = True

    def __init__(self, news_service: NewsService, gemini: GeminiService) -> None:
        self._news_service = news_service
        self._gemini = gemini
        self._logger = logging.getLogger("hdx08.multi_agent.news")

    def run(self, context: AgentContext) -> AgentResult:
        """Store deduplicated articles and Gemini's JSON-only news analysis."""
        updated = context.model_copy(deep=True)
        company_name = updated.metadata.get("company_name")
        fetched = self._news_service.get_news(updated.symbol, company_name=company_name)
        updated.news = [article.model_dump(mode="json") for article in fetched.articles]
        errors = [f"News provider: {error}" for error in fetched.errors]
        analysis = self._gemini.analyze_news({"symbol": updated.symbol, "news": updated.news})
        if isinstance(analysis, NewsAnalysisError):
            errors.append(f"News analysis: {analysis.error}")
            updated.news_analysis = analysis.model_dump(mode="json")
        else:
            updated.news_analysis = analysis.model_dump(mode="json")
        updated.errors.extend(errors)
        status = "success" if not errors else "partial" if updated.news else "failed"
        self._logger.info("agent_news_completed", extra={"request_id": updated.request_id, "symbol": updated.symbol,
                                                          "articles": len(updated.news), "status": status, "errors": len(errors)})
        return AgentResult(status=status, messages=[f"Collected {len(updated.news)} news articles"], errors=errors, updated_context=updated)
