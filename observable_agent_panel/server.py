"""
Observable Agent Control Panel — MCP Server (Data Layer)

Architecture: This server is a PURE DATA LAYER.
- It returns structured raw data: PR diffs, memory matches, traces, anomalies.
- ALL reasoning, planning, and synthesis is done by the IDE agent (Antigravity/Cursor/Cline).
- No internal LLM calls are made by any tool in this server.

Tools available to the IDE agent:
  search_github_prs    — find closed PRs by keyword
  fetch_pr_diff        — get a specific PR's diff and description
  search_memory        — semantic search over indexed engineering knowledge
  index_repo_prs       — index closed PRs into long-term memory
  index_repo_issues    — index closed issues into long-term memory
  search_stackexchange — search StackOverflow for technical answers
  get_recent_traces    — list recent agent runs with IDs and metadata
  get_trace_detail     — get full hop-by-hop detail for a specific run
  analyze_performance  — tool success rates and failure counts
  get_anomaly_alerts   — structured list of active system alerts
  compare_runs         — diff two runs + rule-based root cause analysis

Now supports ASYNC execution.
"""

import json
import os
import sys
import time
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from functools import wraps

# ── Robust path resolution ───────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Redirect stderr to a log file to ensure zero stdout pollution
log_path = os.path.join(ROOT_DIR, "data", "mcp_server.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
sys.stderr = open(log_path, 'a', encoding='utf-8', errors='replace')

load_dotenv(dotenv_path=os.path.join(ROOT_DIR, ".env"))

from observable_agent_panel.core.trace_db import trace_db
from devops_agent.memory.long_term import LongTermMemory
from devops_agent.tools.registry import execute_tool

# ── Trace Decorator for MCP visibility (Async) ───────────────────────────────
def trace_mcp_tool(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        tool_name = func.__name__
        query = f"MCP: {tool_name}"
        if kwargs:
            query += f" {kwargs}"
            
        trace_db.start_trace(query)
        trace_db.update_triage(1.0, "mcp_direct") # Direct tool call
        
        t_start = time.monotonic()
        try:
            result = await func(*args, **kwargs)
            latency_ms = (time.monotonic() - t_start) * 1000
            
            # Determine status from result content
            status = "success"
            if isinstance(result, str):
                try:
                    res_obj = json.loads(result)
                    if res_obj.get("status") in ("error", "empty"):
                        status = res_obj["status"]
                    elif "matches" in res_obj and res_obj.get("count") == 0:
                        status = "empty"
                except: pass
            
            trace_db.log_hop(tool_name, kwargs, status, latency_ms)
            trace_db.finalize_trace(str(result)[:200] + "...")
            return result
        except Exception as e:
            latency_ms = (time.monotonic() - t_start) * 1000
            error_msg = f"Tool execution failed: {str(e)}"
            trace_db.log_hop(tool_name, kwargs, "error", latency_ms)
            trace_db.finalize_trace(f"Error: {str(e)}")
            # Return valid JSON error instead of raising
            return json.dumps({
                "status": "error",
                "message": error_msg,
                "suggestion": "Check logs or try a different query."
            }, ensure_ascii=True)
    return wrapper

# ── Lazy memory (no LLM client needed at startup) ────────────────────────────
_memory: Optional[LongTermMemory] = None

def _get_memory() -> LongTermMemory:
    global _memory
    if _memory is None:
        db_path = os.path.join(ROOT_DIR, "data", "memory.db")
        _memory = LongTermMemory(db_path=db_path)
    return _memory


# ── Lazy orchestrator (only needed for indexing) ──────────────────────────────
_orchestrator = None

def _get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from devops_agent.core.llm_client import LLMClient
        from devops_agent.core.orchestrator import Orchestrator
        _orchestrator = Orchestrator(
            llm_client=LLMClient(),
            long_term=_get_memory(),
        )
    return _orchestrator


mcp = FastMCP("Observable Agent Control Panel")


# ─── GitHub Tools ─────────────────────────────────────────────────────────────

@mcp.tool()
@trace_mcp_tool
async def search_github_prs(query: str, repo: Optional[str] = None) -> str:
    """
    Search for closed PRs matching a keyword query.
    Returns a JSON list of {number, title, url, state}.
    The IDE agent should reason over these results to answer the user's question.
    """
    res = await execute_tool("search_github_prs", {"query": query, "repo": repo})
    return json.dumps(res, indent=2, ensure_ascii=True)


@mcp.tool()
@trace_mcp_tool
async def fetch_pr_diff(pr_number: int, repo: Optional[str] = None) -> str:
    """
    Fetch the diff and description for a specific PR number.
    Returns {title, body, diff, truncated, original_length}.
    The IDE agent should interpret the diff to explain what changed.
    """
    res = await execute_tool("fetch_pr_diff", {"pr_number": pr_number, "repo": repo})
    return json.dumps(res, indent=2, ensure_ascii=True)


# ─── Memory Tools ─────────────────────────────────────────────────────────────

@mcp.tool()
@trace_mcp_tool
async def search_memory(query: str, top_k: int = 5) -> str:
    """
    Semantic search over the indexed engineering knowledge base.
    Returns a JSON list of {issue, resolution, repo_name, score} sorted by relevance.
    The IDE agent should use these matches to ground its answer before calling other tools.
    """
    matches = _get_memory().search_memory(query, top_k=top_k)
    results = [
        {
            "issue": m.get("issue", ""),
            "resolution": m.get("resolution", ""),
            "repo_name": m.get("repo_name", ""),
            "score": round(m.get("score", 0), 4),
        }
        for m in matches
    ]
    return json.dumps({"matches": results, "count": len(results)}, indent=2, ensure_ascii=True)


@mcp.tool()
@trace_mcp_tool
async def index_repo_prs(repo: str, count: int = 10, storage: str = "permanent") -> str:
    """
    Fetch and index the most recent closed PRs from a repository into memory.
    Returns {status, message, indexed_count}.
    """
    res = await _get_orchestrator().index_repo_prs(repo, count, storage)
    return json.dumps(res, indent=2, ensure_ascii=True)


@mcp.tool()
@trace_mcp_tool
async def index_repo_issues(repo: str, count: int = 10, storage: str = "permanent") -> str:
    """
    Fetch and index the most recent closed issues from a repository into memory.
    Returns {status, message, indexed_count}.
    """
    res = await _get_orchestrator().index_repo_issues(repo, count, storage)
    return json.dumps(res, indent=2, ensure_ascii=True)


@mcp.tool()
@trace_mcp_tool
async def search_stackexchange(query: str) -> str:
    """
    Search StackOverflow for threads matching the query.
    Returns JSON with top 5 results.
    """
    res = await execute_tool("search_stackexchange", {"query": query})
    return json.dumps(res, indent=2, ensure_ascii=True)


# ─── Observability Tools ──────────────────────────────────────────────────────

@mcp.tool()
async def get_recent_traces(count: int = 10) -> str:
    """
    List the most recent agent runs with run_ids, routing decisions, and outcomes.
    Returns a JSON list. Use run_id values with get_trace_detail or compare_runs.
    """
    traces = trace_db.get_recent_traces(count)
    summary = [
        {
            "run_id": t["run_id"],
            "timestamp": t.get("timestamp", ""),
            "query": (t.get("query") or "")[:100],
            "routing_decision": t.get("routing_decision"),
            "similarity_score": t.get("similarity_score"),
            "hop_count": len(t.get("hops", [])),
            "hop_limit_hit": t.get("hop_limit_hit", False),
            "outcome": t.get("outcome"),
        }
        for t in traces
    ]
    return json.dumps(summary, indent=2, ensure_ascii=True)


@mcp.tool()
async def get_trace_detail(run_id: str) -> str:
    """
    Get the full hop-by-hop reasoning trace for a specific run.
    Returns {run_id, query, hops: [{tool, status, duration_ms}], explanation}.
    Prefix matching is supported — pass the first 8 chars of a run_id.
    """
    t = trace_db.get_trace(run_id)
    if not t:
        recent = trace_db.get_recent_traces(100)
        matches = [r for r in recent if r["run_id"].startswith(run_id)]
        t = matches[0] if matches else None
    if not t:
        return json.dumps({"error": f"No trace found for run_id '{run_id}'"})
    return json.dumps({
        "run_id": t["run_id"],
        "timestamp": t.get("timestamp"),
        "query": t.get("query"),
        "routing_decision": t.get("routing_decision"),
        "similarity_score": t.get("similarity_score"),
        "hops": t.get("hops", []),
        "hop_limit_hit": t.get("hop_limit_hit", False),
        "outcome": t.get("outcome"),
        "explanation": t.get("explanation"),
        "memory_facts_used": t.get("memory_facts_used", []),
    }, indent=2, ensure_ascii=True)


@mcp.tool()
async def analyze_performance() -> str:
    """
    Return tool usage success rates and failure counts across recent runs.
    Returns {total_runs, success_rate, knowledge_gaps, hop_limit_hits, tool_stats}.
    """
    from observable_agent_panel.core.analyzer import get_failure_report_data
    traces = trace_db.get_recent_traces(100)
    return json.dumps(get_failure_report_data(traces), indent=2, ensure_ascii=True)


@mcp.tool()
async def get_anomaly_alerts() -> str:
    """
    Return a list of active system anomalies (tool failure spikes, low similarity, etc.).
    Returns a JSON list of {type, message, severity}.
    Empty list means all systems nominal.
    """
    from observable_agent_panel.core.analyzer import get_anomaly_alerts_data
    traces = trace_db.get_recent_traces(50)
    alerts = get_anomaly_alerts_data(traces)
    return json.dumps({"alerts": alerts, "count": len(alerts)}, indent=2, ensure_ascii=True)


@mcp.tool()
async def search_traces(query: str, limit: int = 10) -> str:
    """
    Search historical agent run logs for specific keywords, error messages, or queries.
    Returns a JSON list of {run_id, timestamp, query, final_answer, outcome, explanation}.
    Use this to find out what errors the system has faced in the past or to summarize previous diagnostic sessions.
    """
    res = trace_db.search_traces(query, limit)
    return json.dumps(res, indent=2, ensure_ascii=True)


@mcp.tool()
async def compare_runs(run_id_a: str, run_id_b: str) -> str:
    """
    Diff two agent runs side-by-side and generate a root cause analysis.
    Returns {run_a, run_b, diff_fields, root_cause_insights}.
    The IDE agent can use these insights to explain regressions or improvements.
    """
    from observable_agent_panel.core.analyzer import root_cause_analysis as _root_cause

    def _resolve(run_id: str) -> Optional[Dict]:
        t = trace_db.get_trace(run_id)
        if not t:
            recent = trace_db.get_recent_traces(100)
            matches = [r for r in recent if r["run_id"].startswith(run_id)]
            return matches[0] if matches else None
        return t

    t1 = _resolve(run_id_a)
    t2 = _resolve(run_id_b)

    if not t1 or not t2:
        return json.dumps({"error": "One or both run IDs not found."})

    def _summary(t):
        return {
            "run_id": t["run_id"],
            "query": t.get("query"),
            "routing_decision": t.get("routing_decision"),
            "similarity_score": t.get("similarity_score"),
            "hop_count": len(t.get("hops", [])),
            "hop_limit_hit": t.get("hop_limit_hit", False),
            "outcome": t.get("outcome"),
        }

    root_cause_text = _root_cause(t1, t2)
    insights = [line.strip().lstrip("• ") for line in root_cause_text.split("\n") if line.strip()]

    return json.dumps({
        "run_a": _summary(t1),
        "run_b": _summary(t2),
        "root_cause_insights": insights,
    }, indent=2, ensure_ascii=True)



# ─── Self-Healing Loop Tools ──────────────────────────────────────────────────

@mcp.tool()
async def get_failure_candidates(limit: int = 5) -> str:
    """
    Find recent agent runs that failed — either human-rated bad (outcome=n)
    or containing tool errors/empty results. This is the entry point for the
    self-healing loop. Returns {failures: [...], total_found: N}.
    """
    from observable_agent_panel.core.self_healing import get_failure_candidates as _get_failures
    failures, total = _get_failures(limit)
    return json.dumps({"failures": failures, "total_found": total}, indent=2, ensure_ascii=True)


@mcp.tool()
async def deep_diagnose_failures(run_ids: List[str]) -> str:
    """
    Perform an LLM-powered deep dive into multiple failed runs.
    Returns a synthesized report with root causes and suggested external search queries.
    """
    from observable_agent_panel.core.analyzer import deep_failure_analysis
    
    traces = []
    for rid in run_ids:
        t = trace_db.get_trace(rid)
        if not t:
            recent = trace_db.get_recent_traces(100)
            matches = [r for r in recent if r["run_id"].startswith(rid)]
            t = matches[0] if matches else None
        if t:
            traces.append(t)
            
    if not traces:
        return json.dumps({"error": "No valid run IDs provided."})
        
    report = await deep_failure_analysis(traces)
    return json.dumps({"report": report}, indent=2, ensure_ascii=True)


@mcp.tool()
async def propose_fix(run_id: str, root_cause: str) -> str:
    """
    Given a failed run_id and the root cause string from compare_runs,
    returns a structured fix proposal. Rule-based — no LLM call.
    Returns {fix_type, fix_action, fix_params, requires_human_approval}.
    """
    from observable_agent_panel.core.self_healing import propose_fix as _propose
    res = await _propose(run_id, root_cause)
    return json.dumps(res, indent=2, ensure_ascii=True)


@mcp.tool()
async def verify_fix(original_run_id: str, new_run_id: str) -> str:
    """
    Compare a failed run against a new run to verify whether a fix worked.
    Returns {verdict: FIXED|NOT_FIXED, fix_verified, root_cause_insights, run summaries}.
    Use this after applying a fix to confirm the agent now handles the query correctly.
    """
    from observable_agent_panel.core.self_healing import verify_fix as _verify
    res = _verify(original_run_id, new_run_id)
    return json.dumps(res, indent=2, ensure_ascii=True)


def main():
    """Run the MCP server using stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
