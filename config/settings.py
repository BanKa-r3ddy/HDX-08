"""Environment-backed application settings."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration loaded once at application startup."""

    database_path: Path = Path(os.getenv("HDX_DATABASE_PATH", "data/hdx08.sqlite3"))
    log_level: str = os.getenv("HDX_LOG_LEVEL", "INFO")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")


settings = Settings()
