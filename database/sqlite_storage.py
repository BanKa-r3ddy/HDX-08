"""SQLite adapter for auditable analysis records."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any


class SQLiteStorage:
    """Stores analysis output; it never stores or executes orders."""

    def __init__(self, database_path: Path) -> None:
        self._path = database_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        """Create the schema if it is absent."""
        with sqlite3.connect(self._path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS analyses (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")

    def save_analysis(self, symbol: str, payload: dict[str, Any]) -> int:
        """Persist a serialized analysis and return its database ID."""
        with sqlite3.connect(self._path) as connection:
            cursor = connection.execute("INSERT INTO analyses(symbol, payload) VALUES (?, ?)", (symbol, json.dumps(payload)))
            return int(cursor.lastrowid)
