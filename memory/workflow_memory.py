"""Workflow-scoped memory objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkflowMemory:
    """Carries typed-enough intermediate results between analysis stages."""

    symbol: str
    values: dict[str, Any] = field(default_factory=dict)

    def put(self, key: str, value: Any) -> None:
        """Store an intermediate value."""
        self.values[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Return a value, or a caller-supplied default."""
        return self.values.get(key, default)
