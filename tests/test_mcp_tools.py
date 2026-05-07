"""
Tests for the three self-healing loop MCP tools:
  get_failure_candidates, propose_fix, verify_fix
Updated for ASYNC support.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import observable_agent_panel.server as server


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_trace(run_id="run-abc", outcome=None, hops=None, similarity=0.5,
                routing="tools_only", query="test query"):
    return {
        "run_id": run_id,
        "timestamp": "2026-05-01T10:00:00",
        "query": query,
        "similarity_score": similarity,
        "routing_decision": routing,
        "hops": hops or [],
        "hop_limit_hit": False,
        "outcome": outcome,
        "explanation": None,
        "memory_facts_used": [],
    }


def _failed_hop(tool="search_github_prs"):
    return {"tool": tool, "status": "error", "arguments": {}, "latency_ms": 200}


def _success_hop(tool="search_github_prs"):
    return {"tool": tool, "status": "success", "arguments": {}, "latency_ms": 100}


# ─── get_failure_candidates ───────────────────────────────────────────────────

class TestGetFailureCandidates:
    @pytest.mark.asyncio
    async def test_returns_only_failures(self):
        """Only runs with outcome=n or tool errors are returned."""
        good = _make_trace("run-good", outcome="y", hops=[_success_hop()])
        bad_outcome = _make_trace("run-bad1", outcome="n")
        bad_tool = _make_trace("run-bad2", hops=[_failed_hop()])

        with patch.object(server.trace_db, "get_recent_traces", return_value=[good, bad_outcome, bad_tool]):
            result = json.loads(await server.get_failure_candidates(limit=10))

        run_ids = [f["run_id"] for f in result["failures"]]
        assert "run-bad1" in run_ids
        assert "run-bad2" in run_ids
        assert "run-good" not in run_ids

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        """limit parameter caps the returned failures."""
        traces = [_make_trace(f"run-{i}", outcome="n") for i in range(10)]

        with patch.object(server.trace_db, "get_recent_traces", return_value=traces):
            result = json.loads(await server.get_failure_candidates(limit=3))

        assert len(result["failures"]) == 3
        assert result["total_found"] == 10

    @pytest.mark.asyncio
    async def test_empty_traces_returns_empty(self):
        """No traces → empty failures list."""
        with patch.object(server.trace_db, "get_recent_traces", return_value=[]):
            result = json.loads(await server.get_failure_candidates())
        assert result["failures"] == []
        assert result["total_found"] == 0

    @pytest.mark.asyncio
    async def test_includes_failed_tool_names(self):
        """failed_tools field lists the names of tools that errored."""
        trace = _make_trace("run-x", hops=[
            _failed_hop("search_github_prs"),
            _success_hop("fetch_pr_diff"),
        ])
        with patch.object(server.trace_db, "get_recent_traces", return_value=[trace]):
            result = json.loads(await server.get_failure_candidates())
        assert result["failures"][0]["failed_tools"] == ["search_github_prs"]


# ─── propose_fix ─────────────────────────────────────────────────────────────

class TestProposeFix:
    async def _call(self, run_id, root_cause, trace=None, llm_response=None):
        if trace is None:
            trace = _make_trace(run_id)
        
        # Default mock response if none provided
        if llm_response is None:
            llm_response = json.dumps({
                "fix_type": "manual_review",
                "fix_action": "Manual review required",
                "fix_params": {}
            })

        with patch.object(server.trace_db, "get_trace", return_value=trace), \
             patch("devops_agent.core.llm_client.LLMClient") as mock_llm_class:
            
            mock_llm = mock_llm_class.return_value
            mock_llm.simple_chat = AsyncMock(return_value=llm_response)
            
            return json.loads(await server.propose_fix(run_id, root_cause))

    @pytest.mark.asyncio
    async def test_knowledge_gap_returns_index_action(self):
        resp = json.dumps({
            "fix_type": "index_more_data",
            "fix_action": "Index tiangolo/fastapi",
            "fix_params": {"tool": "index_repo_prs", "repo": "tiangolo/fastapi", "count": 50}
        })
        result = await self._call("run-1", "KNOWLEDGE GAP: Run B had low memory similarity (0.08)", llm_response=resp)
        assert result["fix_type"] == "index_more_data"
        assert result["fix_params"]["tool"] == "index_repo_prs"
        assert result["requires_human_approval"] is True

    @pytest.mark.asyncio
    async def test_github_tool_failure_returns_config_action(self):
        resp = json.dumps({
            "fix_type": "tool_config",
            "fix_action": "Check GITHUB_TOKEN",
            "fix_params": {"tool": "search_github_prs", "action": "check_auth"}
        })
        result = await self._call("run-1", "TOOL FAILURE in Run A: search_github_prs returned no results", llm_response=resp)
        assert result["fix_type"] == "tool_config"
        assert result["fix_params"]["tool"] == "search_github_prs"

    @pytest.mark.asyncio
    async def test_stackexchange_failure_returns_config_action(self):
        resp = json.dumps({
            "fix_type": "tool_config",
            "fix_action": "Check StackExchange API",
            "fix_params": {"tool": "search_stackexchange"}
        })
        result = await self._call("run-1", "TOOL FAILURE in Run A: search_stackexchange returned error", llm_response=resp)
        assert result["fix_type"] == "tool_config"
        assert result["fix_params"]["tool"] == "search_stackexchange"

    @pytest.mark.asyncio
    async def test_hop_limit_returns_index_action(self):
        resp = json.dumps({
            "fix_type": "index_more_data",
            "fix_action": "Increase indexing depth",
            "fix_params": {}
        })
        result = await self._call("run-1", "EFFICIENCY DELTA: hop limit exhausted after 5 hops", llm_response=resp)
        assert result["fix_type"] == "index_more_data"

    @pytest.mark.asyncio
    async def test_unknown_root_cause_returns_manual_review(self):
        # Using default manual_review mock
        result = await self._call("run-1", "Something completely unexpected happened here")
        assert result["fix_type"] == "manual_review"
        assert result["fix_params"] == {}

    @pytest.mark.asyncio
    async def test_missing_run_id_returns_error(self):
        with patch.object(server.trace_db, "get_trace", return_value=None), \
             patch.object(server.trace_db, "get_recent_traces", return_value=[]), \
             patch("devops_agent.core.llm_client.LLMClient"):
            result = json.loads(await server.propose_fix("nonexistent", "knowledge gap"))
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_includes_original_query(self):
        trace = _make_trace("run-1", query="How was pydantic v2 fixed?")
        result = await self._call("run-1", "knowledge gap similarity low", trace=trace)
        assert result["original_query"] == "How was pydantic v2 fixed?"


# ─── verify_fix ───────────────────────────────────────────────────────────────

class TestVerifyFix:
    async def _call(self, original, new_run):
        def _get_trace(rid):
            return original if rid == original["run_id"] else new_run

        with patch.object(server.trace_db, "get_trace", side_effect=_get_trace):
            return json.loads(await server.verify_fix(original["run_id"], new_run["run_id"]))

    @pytest.mark.asyncio
    async def test_returns_fixed_when_outcome_improved(self):
        """outcome n → y with higher similarity = FIX VERIFIED."""
        orig = _make_trace("run-old", outcome="n", similarity=0.05, routing="tools_only")
        new = _make_trace("run-new", outcome="y", similarity=0.92, routing="memory_only")
        result = await self._call(orig, new)
        assert result["verdict"] == "FIXED"
        assert result["fix_verified"] is True

    @pytest.mark.asyncio
    async def test_returns_not_fixed_when_outcome_same_bad(self):
        """Both outcome=n = NOT_FIXED."""
        orig = _make_trace("run-old", outcome="n", similarity=0.05)
        new = _make_trace("run-new", outcome="n", similarity=0.10)
        result = await self._call(orig, new)
        assert result["verdict"] == "NOT_FIXED"
        assert result["fix_verified"] is False

    @pytest.mark.asyncio
    async def test_returns_not_fixed_when_no_change(self):
        """Structurally identical runs = not fixed."""
        orig = _make_trace("run-old", outcome="y", similarity=0.8, routing="hybrid")
        new = _make_trace("run-new", outcome="y", similarity=0.8, routing="hybrid")
        result = await self._call(orig, new)
        assert result["verdict"] == "NOT_FIXED"  # no improvement detected

    @pytest.mark.asyncio
    async def test_detects_regression(self):
        """outcome y → n = regression."""
        orig = _make_trace("run-old", outcome="y", similarity=0.9, routing="memory_only")
        new = _make_trace("run-new", outcome="n", similarity=0.05, routing="tools_only")
        result = await self._call(orig, new)
        assert result.get("regression_detected") is True

    @pytest.mark.asyncio
    async def test_handles_missing_run_id(self):
        """Missing run returns error status."""
        with patch.object(server.trace_db, "get_trace", return_value=None), \
             patch.object(server.trace_db, "get_recent_traces", return_value=[]):
            result = json.loads(await server.verify_fix("missing-a", "missing-b"))
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_includes_run_summaries(self):
        """Both run summaries are included in the result."""
        orig = _make_trace("run-old", outcome="n", similarity=0.1)
        new = _make_trace("run-new", outcome="y", similarity=0.95)
        result = await self._call(orig, new)
        assert result["original_run"]["run_id"] == "run-old"
        assert result["new_run"]["run_id"] == "run-new"
        assert "similarity_score" in result["original_run"]

    @pytest.mark.asyncio
    async def test_includes_root_cause_insights(self):
        """root_cause_insights is a non-empty list of strings."""
        orig = _make_trace("run-old", outcome="n", similarity=0.05, routing="tools_only")
        new = _make_trace("run-new", outcome="y", similarity=0.9, routing="memory_only")
        result = await self._call(orig, new)
        assert isinstance(result["root_cause_insights"], list)
        assert len(result["root_cause_insights"]) > 0
