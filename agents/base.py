"""Shared agent contracts."""
from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import Any

from memory.workflow_memory import WorkflowMemory


class AnalysisAgent(ABC):
    """Base class for a single, observable analysis responsibility."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.logger = logging.getLogger(f"hdx08.agents.{name}")

    @abstractmethod
    def run(self, memory: WorkflowMemory) -> dict[str, Any]:
        """Perform the agent's bounded analysis task."""
