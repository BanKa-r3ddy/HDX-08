"""SQLite-backed local memory agent."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3

from .models import AgentContext, AgentResult


class MemoryAgent:
    """Persists a compact, auditable analysis memory record in SQLite."""

    name = "Memory"
    enabled_by_default = True

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._logger = logging.getLogger("hdx08.multi_agent.memory")
        self._initialize()

    def run(self, context: AgentContext) -> AgentResult:
        """Store request, symbol, timestamp, AI summary, confidence, and trend."""
        updated = context.model_copy(deep=True)
        ai = updated.ai_analysis or {}
        technical = updated.technical_analysis or {}
        summary = ai.get("market_summary", "Insufficient Data")
        confidence = ai.get("confidence")
        trend = technical.get("summary", {}).get("trend", "Insufficient Data")
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            with sqlite3.connect(self._database_path) as connection:
                cursor = connection.execute(
                    "INSERT INTO agent_memory(request_id, symbol, timestamp, ai_summary, confidence, trend) VALUES (?, ?, ?, ?, ?, ?)",
                    (updated.request_id, updated.symbol, timestamp, summary, confidence, trend),
                )
            updated.memory["record_id"] = int(cursor.lastrowid)
            updated.memory["timestamp"] = timestamp
            self._logger.info("agent_memory_stored", extra={"request_id": updated.request_id, "symbol": updated.symbol, "record_id": cursor.lastrowid})
            return AgentResult(status="success", messages=["Local memory stored"], updated_context=updated)
        except sqlite3.Error as exc:
            error = f"Memory storage: {exc}"
            updated.errors.append(error)
            self._logger.error("agent_memory_failed", extra={"request_id": updated.request_id, "error": str(exc)})
            return AgentResult(status="failed", errors=[error], updated_context=updated)

    def _initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_memory ("
                "id INTEGER PRIMARY KEY, request_id TEXT NOT NULL, symbol TEXT NOT NULL, "
                "timestamp TEXT NOT NULL, ai_summary TEXT NOT NULL, confidence INTEGER, trend TEXT NOT NULL)"
            )
