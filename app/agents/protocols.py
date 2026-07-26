"""Protocols supporting dependency-injected, replaceable agents."""
from __future__ import annotations

from typing import Protocol

from .models import AgentContext, AgentResult


class AnalysisAgent(Protocol):
    """Contract understood by the orchestrator and future plug-in agents."""

    name: str
    enabled_by_default: bool

    def run(self, context: AgentContext) -> AgentResult:
        """Return an updated context without raising expected operational failures."""
