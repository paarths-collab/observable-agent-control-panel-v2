import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from observable_agent_panel.core.self_healing import get_failure_candidates, propose_fix, verify_fix

@pytest.mark.asyncio
@patch("observable_agent_panel.core.self_healing.trace_db")
async def test_get_failure_candidates(mock_db):
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

@pytest.mark.asyncio
@patch("observable_agent_panel.core.self_healing.trace_db")
@patch("devops_agent.core.llm_client.LLMClient")
async def test_propose_fix_knowledge_gap(mock_llm_class, mock_db):
    mock_db.get_trace.return_value = {
        "run_id": "run-123",
        "query": "Recent PRs in FastAPI"
    }
    
    mock_llm = mock_llm_class.return_value
    mock_llm.simple_chat = AsyncMock(return_value='{"fix_type": "index_more_data", "fix_action": "Index tiangolo/fastapi", "fix_params": {"tool": "index_repo_prs", "repo": "tiangolo/fastapi", "count": 50}, "explanation": "test"}')
    
    proposal = await propose_fix("run-123", "Knowledge gap: low similarity score")
    assert proposal["fix_type"] == "index_more_data"
    assert "tiangolo/fastapi" in proposal["fix_action"]
    assert proposal["fix_params"]["tool"] == "index_repo_prs"

@pytest.mark.asyncio
@patch("observable_agent_panel.core.self_healing.trace_db")
@patch("devops_agent.core.llm_client.LLMClient")
async def test_propose_fix_tool_failure(mock_llm_class, mock_db):
    mock_db.get_trace.return_value = {
        "run_id": "run-456",
        "query": "Search Django bugs"
    }
    
    mock_llm = mock_llm_class.return_value
    mock_llm.simple_chat = AsyncMock(return_value='{"fix_type": "tool_config", "fix_action": "Check GITHUB_TOKEN", "fix_params": {"tool": "search_github_prs", "action": "check_auth"}, "explanation": "test"}')
    
    proposal = await propose_fix("run-456", "Tool failure: github search error")
    assert proposal["fix_type"] == "tool_config"
    assert "GITHUB_TOKEN" in proposal["fix_action"]

@pytest.mark.asyncio
@patch("observable_agent_panel.core.self_healing.trace_db")
@patch("observable_agent_panel.core.self_healing.root_cause_analysis")
async def test_verify_fix(mock_rca, mock_db):
    mock_db.get_trace.side_effect = [
        {"run_id": "old-1", "outcome": "n", "hops": []},
        {"run_id": "new-1", "outcome": "y", "hops": [{"tool": "test", "status": "success"}]}
    ]
    mock_rca.return_value = "• FIX VERIFIED: Success rate improved"
    
    result = verify_fix("old-1", "new-1")
    assert result["verdict"] == "FIXED"
    assert result["fix_verified"] is True
    assert result["new_run"]["run_id"] == "new-1"
