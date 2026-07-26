"""Run a small offline health check for HDX-08."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import build_workflow

if __name__ == "__main__":
    result = build_workflow().analyze("HDX")
    assert result["workflow"]["decision"]["executable"] is False
    print(f"Health check passed: analysis #{result['analysis_id']}")
