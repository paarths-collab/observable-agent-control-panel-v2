import pytest
from unittest.mock import MagicMock, patch
from observable_agent_panel.core.self_healing import get_failure_candidates, propose_fix, verify_fix

@patch("observable_agent_panel.core.self_healing.trace_db")
def test_get_failure_candidates(mock_db):
    # Mock data: one failure, one success
    mock_db.get_recent_traces.return_value = [
        {
            "run_id": "fail-1",
            "outcome": "n",
            "query": "Fix this OOM",
            "hops": [{"tool": "search", "status": "error"}]
        },
        {
            "run_id": "success-1",
            "outcome": "y",
            "query": "Status check",
            "hops": [{"tool": "check", "status": "success"}]
        }
    ]
    
    candidates, total = get_failure_candidates(limit=5)
    assert len(candidates) == 1
    assert total == 1
    assert candidates[0]["run_id"] == "fail-1"
    assert "search" in candidates[0]["failed_tools"]

@patch("observable_agent_panel.core.self_healing.trace_db")
def test_propose_fix_knowledge_gap(mock_db):
    mock_db.get_trace.return_value = {
        "run_id": "run-123",
        "query": "Recent PRs in FastAPI"
    }
    
    proposal = propose_fix("run-123", "Knowledge gap: low similarity score")
    assert proposal["fix_type"] == "index_more_data"
    assert "tiangolo/fastapi" in proposal["fix_action"]
    assert proposal["fix_params"]["tool"] == "index_repo_prs"

@patch("observable_agent_panel.core.self_healing.trace_db")
def test_propose_fix_tool_failure(mock_db):
    mock_db.get_trace.return_value = {
        "run_id": "run-456",
        "query": "Search Django bugs"
    }
    
    proposal = propose_fix("run-456", "Tool failure: github search error")
    assert proposal["fix_type"] == "tool_config"
    assert "GITHUB_TOKEN" in proposal["fix_action"]

@patch("observable_agent_panel.core.self_healing.trace_db")
@patch("observable_agent_panel.core.self_healing.root_cause_analysis")
def test_verify_fix(mock_rca, mock_db):
    mock_db.get_trace.side_effect = [
        {"run_id": "old-1", "outcome": "n", "hops": []},
        {"run_id": "new-1", "outcome": "y", "hops": [{"tool": "test", "status": "success"}]}
    ]
    mock_rca.return_value = "• FIX VERIFIED: Success rate improved"
    
    result = verify_fix("old-1", "new-1")
    assert result["verdict"] == "FIXED"
    assert result["fix_verified"] is True
    assert result["new_run"]["run_id"] == "new-1"
