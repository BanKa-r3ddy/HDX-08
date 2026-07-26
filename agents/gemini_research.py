"""Optional Google ADK / Gemini research-agent integration boundary."""
from __future__ import annotations

from google.adk.agents import Agent


def build_gemini_research_agent(model: str = "gemini-2.5-flash") -> Agent:
    """Create a non-executing ADK agent for future research summarization.

    The returned ADK agent has no tools capable of order placement or broker
    access. Supplying `GEMINI_API_KEY` is required only when a caller runs it.
    """
    return Agent(
        name="hdx08_research",
        model=model,
        instruction=(
            "You are a financial research assistant. Summarize supplied data, "
            "state uncertainty, and never recommend or execute an order. "
            "You have no broker access."
        ),
    )
