"""
Integration tests for the observability layer wired into the Orchestrator.
Updated for ASYNC support.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from devops_agent.core.orchestrator import Orchestrator, HIGH_CONFIDENCE, HYBRID_THRESHOLD
from observable_agent_panel.core.trace_db import TraceDB
from devops_agent.core.llm_client import LLMClient
from devops_agent.memory.long_term import LongTermMemory


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_db(tmp_path):
    """An isolated TraceDB backed by a temp file."""
    db = TraceDB(db_path=str(tmp_path / "test_traces.db"))
    return db


@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=LLMClient)
    
    # triage_json = json.dumps({"intent": "tools_only", "reasoning": "test"})
    
    def simple_chat_side_effect(messages):
        # Identify triage vs answer vs explanation
        system_content = messages[0]["content"] if messages else ""
        if "Classify the user's query into one of these intents" in system_content:
            # Detect intended routing from query if needed, or default
            query = messages[-1]["content"].lower()
            if "cors" in query or "auth" in query:
                return json.dumps({"intent": "memory_only", "reasoning": "matched query keyword"})
            if "diagnostic" in query or "failure" in query:
                return json.dumps({"intent": "diagnostic", "reasoning": "diagnostic keyword"})
            return json.dumps({"intent": "tools_only", "reasoning": "test default"})
            
        if "DevOps observability assistant" in system_content:
            return "Plain English explanation."
            
        return "Mocked LLM answer."

    llm.simple_chat = AsyncMock(side_effect=simple_chat_side_effect)
    
    # Minimal valid tool-response: no tool_calls → stop immediately
    llm.chat = AsyncMock(return_value={
        "choices": [{"message": {"content": "Mocked tool answer.", "tool_calls": None}}]
    })
    llm.summarize_for_memory = AsyncMock(return_value={"issue": "test", "fix": "test", "repo_name": "test", "tags": []})
    return llm


@pytest.fixture
def orchestrator(mock_llm, isolated_db):
    memory = LongTermMemory(db_path=":memory:")
    orch = Orchestrator(llm_client=mock_llm, long_term=memory)
    # Patch global singleton so orchestrator writes to our isolated db
    with patch("devops_agent.core.orchestrator.trace_db", isolated_db):
        yield orch, isolated_db


# ─── Memory-only path ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_memory_path_creates_trace(orchestrator):
    orch, db = orchestrator
    query = "How do I fix CORS in FastAPI?"

    # Plant a high-confidence match in memory
    high_score_match = {
        "score": HIGH_CONFIDENCE + 0.05,
        "issue": "CORS issue",
        "fix": "Add CORSMiddleware",
        "context": "...",
        "repo_name": "test/repo",
        "tags": [],
    }
    orch.memory.search_memory = MagicMock(return_value=[high_score_match])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    await orch.process_query(query)

    traces = db.get_recent_traces(1)
    assert len(traces) == 1
    t = traces[0]
    assert t["query"] == query
    assert t["routing_decision"] == "memory_only (llm_intent)"
    assert t["similarity_score"] >= HIGH_CONFIDENCE
    assert t["final_answer"] == "Mocked LLM answer."
    assert t["hop_limit_hit"] == 0
    assert t["explanation"] is not None


@pytest.mark.asyncio
async def test_memory_path_records_facts_used(orchestrator):
    orch, db = orchestrator
    high_score_match = {
        "score": HIGH_CONFIDENCE + 0.05,
        "issue": "JWT auth bug",
        "fix": "Check scope",
        "context": "",
        "repo_name": "test/repo",
        "tags": [],
    }
    orch.memory.search_memory = MagicMock(return_value=[high_score_match])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    await orch.process_query("auth issue")

    t = db.get_recent_traces(1)[0]
    assert "JWT auth bug" in t["memory_facts_used"]


# ─── Tools-first path ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tools_path_creates_trace(orchestrator):
    orch, db = orchestrator
    orch.memory.search_memory = MagicMock(return_value=[])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    await orch.process_query("What is a totally unknown error?")

    traces = db.get_recent_traces(1)
    assert len(traces) == 1
    t = traces[0]
    assert t["routing_decision"] == "tools_only"
    assert t["final_answer"] == "Mocked tool answer."
    assert t["hop_limit_hit"] == 0


@pytest.mark.asyncio
async def test_tools_path_records_hop(orchestrator):
    orch, db = orchestrator

    # First LLM call returns a tool_call, second call returns a final answer
    tool_call_response = {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "tc-1",
                    "function": {
                        "name": "search_github_prs",
                        "arguments": json.dumps({"query": "bug", "repo": "test/repo"}),
                    },
                }],
            }
        }]
    }
    final_response = {
        "choices": [{"message": {"content": "Fixed it.", "tool_calls": None}}]
    }
    orch.llm.chat.side_effect = [tool_call_response, final_response]
    orch.memory.search_memory = MagicMock(return_value=[])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    with patch("devops_agent.core.orchestrator.execute_tool", AsyncMock(return_value={"status": "success", "results": []})):
        await orch.process_query("find a bug")

    t = db.get_recent_traces(1)[0]
    assert len(t["hops"]) == 1
    assert t["hops"][0]["tool"] == "search_github_prs"
    assert t["hops"][0]["status"] == "success"
    assert t["hops"][0]["latency_ms"] is not None


# ─── Hop-limit exhaustion path ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hop_limit_records_flag(orchestrator):
    orch, db = orchestrator

    # Every LLM call returns a tool_call, forcing the loop to run until MAX_TOOL_HOPS
    tool_call_response = {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "tc-1",
                    "function": {
                        "name": "search_github_prs",
                        "arguments": json.dumps({"query": "x", "repo": "a/b"}),
                    },
                }],
            }
        }]
    }
    orch.llm.chat.side_effect = None
    orch.llm.chat.return_value = tool_call_response
    orch.memory.search_memory = MagicMock(return_value=[])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    with patch("devops_agent.core.orchestrator.execute_tool", AsyncMock(return_value={"status": "success"})):
        result = await orch.process_query("impossible query")

    t = db.get_recent_traces(1)[0]
    assert t["hop_limit_hit"] == 1
    assert "System Error" in t["final_answer"]


# ─── Multiple sequential runs ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_runs_each_get_unique_trace(orchestrator):
    orch, db = orchestrator
    orch.memory.search_memory = MagicMock(return_value=[])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    await orch.process_query("query one")
    await orch.process_query("query two")
    await orch.process_query("query three")

    traces = db.get_recent_traces(10)
    assert len(traces) == 3
    run_ids = {t["run_id"] for t in traces}
    assert len(run_ids) == 3  # all unique


# ─── Outcome labeling ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_outcome_can_be_set_after_run(orchestrator):
    orch, db = orchestrator
    orch.memory.search_memory = MagicMock(return_value=[])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    await orch.process_query("any query")
    db.set_outcome("n")

    t = db.get_recent_traces(1)[0]
    assert t["outcome"] == "n"
