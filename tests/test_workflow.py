"""Workflow integration tests."""
from main import build_workflow

def test_workflow_is_analysis_only() -> None:
    result = build_workflow().analyze("aapl")
    assert result["symbol"] == "AAPL"
    assert result["workflow"]["decision"]["executable"] is False
    assert result["analysis_id"] > 0
