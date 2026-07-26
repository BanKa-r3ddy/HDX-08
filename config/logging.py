"""Logging configuration."""
from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(level: str = "INFO") -> None:
    """Configure structured, idempotent console and file logging."""
    root = logging.getLogger()
    if root.handlers:
        return
    Path("logs").mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    root.setLevel(level.upper())
    for handler in (logging.StreamHandler(), logging.FileHandler("logs/hdx08.log", encoding="utf-8")):
        handler.setFormatter(formatter)
        root.addHandler(handler)
