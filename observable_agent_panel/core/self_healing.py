"""
Deterministic self-healing logic for the Observable Agent Control Panel.
Follows the 6-step protocol: Find -> Diagnose -> Propose -> Approve -> Apply -> Verify.
"""

import json
from typing import Any, Dict, List, Optional
from observable_agent_panel.core.trace_db import trace_db
from observable_agent_panel.core.analyzer import root_cause_analysis

def get_failure_candidates(limit: int = 5) -> List[Dict[str, Any]]:
    """Find recent agent runs that failed."""
    traces = trace_db.get_recent_traces(50)
    failures = [
        t for t in traces
        if t.get("outcome") == "n"
        or any(h.get("status") in ("error", "empty") for h in t.get("hops", []))
    ]
    summaries = [
        {
            "run_id": t["run_id"],
            "timestamp": t.get("timestamp", ""),
            "query": t.get("query") or "",
            "routing_decision": t.get("routing_decision"),
            "similarity_score": t.get("similarity_score"),
            "outcome": t.get("outcome"),
            "failed_tools": [
                h.get("tool") for h in t.get("hops", [])
                if h.get("status") in ("error", "empty")
            ],
        }
        for t in failures[:limit]
    ]
    return summaries, len(failures)

async def propose_fix(run_id: str, root_cause: str) -> Dict[str, Any]:
    """Rule-based fix proposal."""
    t = trace_db.get_trace(run_id)
    if not t:
        # Try prefix match
        recent = trace_db.get_recent_traces(100)
        matches = [r for r in recent if r["run_id"].startswith(run_id)]
        t = matches[0] if matches else None
    
    if not t:
        return {"status": "error", "message": f"Run '{run_id}' not found."}

    from observable_agent_panel.core.analyzer import generate_dynamic_fix
    
    # Generate a dynamic proposal via LLM reasoning
    fix = await generate_dynamic_fix(t, root_cause)
    
    # Ensure standard fields exist for CLI compatibility
    fix_type = fix.get("fix_type", "manual_review")
    fix_action = fix.get("fix_action", "Manual review required")
    fix_params = fix.get("fix_params", {})

    return {
        "run_id": run_id,
        "original_query": t.get("query"),
        "fix_type": fix_type,
        "fix_action": fix_action,
        "fix_params": fix_params,
        "requires_human_approval": True,
    }

def verify_fix(original_run_id: str, new_run_id: str) -> Dict[str, Any]:
    """Compare runs to verify fix."""
    def _resolve(rid: str) -> Optional[Dict]:
        t = trace_db.get_trace(rid)
        if not t:
            recent = trace_db.get_recent_traces(100)
            matches = [r for r in recent if r["run_id"].startswith(rid)]
            return matches[0] if matches else None
        return t

    original = _resolve(original_run_id)
    new_run = _resolve(new_run_id)

    if not original or not new_run:
        return {"status": "error", "message": "One or both run IDs not found."}

    rca_text = root_cause_analysis(original, new_run)
    insights = [line.strip().lstrip("• ") for line in rca_text.split("\n") if line.strip()]

    fix_verified = any("FIX VERIFIED" in i for i in insights)
    regression = any("REGRESSION" in i for i in insights)

    def _summary(t: Dict) -> Dict:
        return {
            "run_id": t["run_id"],
            "outcome": t.get("outcome"),
            "similarity_score": t.get("similarity_score"),
            "routing_decision": t.get("routing_decision"),
            "hop_count": len(t.get("hops", [])),
        }

    return {
        "verdict": "FIXED" if fix_verified else "NOT_FIXED",
        "fix_verified": fix_verified,
        "regression_detected": regression,
        "original_run": _summary(original),
        "new_run": _summary(new_run),
        "root_cause_insights": insights,
    }
