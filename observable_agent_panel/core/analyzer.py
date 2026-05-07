"""
Failure analysis and anomaly alerting for Observable Agent Control Panel.

Run via:  python cli.py --analyze
          python cli.py --alerts
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Lazy import to avoid circular dependencies
def _get_llm():
    from devops_agent.core.llm_client import LLMClient
    return LLMClient()

import sys
console = Console(file=sys.stderr)

# ─── Alert thresholds ────────────────────────────────────────────────────────
ALERT_TOOL_FAIL_RATE = 0.50      # warn if a tool fails > 50 % of calls
ALERT_LOW_SIMILARITY  = 0.40     # warn if avg similarity drops below this
ALERT_HOP_LIMIT_RATE  = 0.30     # warn if > 30 % of recent runs hit hop limit
RECENT_WINDOW         = 10       # number of runs used for alert calculations


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _tool_stats(traces: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Returns {tool_name: {total, failed}} across all hops."""
    stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "failed": 0})
    for t in traces:
        for hop in t.get("hops", []):
            name = hop.get("tool", "unknown")
            stats[name]["total"] += 1
            if hop.get("status") in ("error", "empty"):
                stats[name]["failed"] += 1
    return stats


# ─── Feature 2: Failure report ────────────────────────────────────────────────
def print_failure_report(traces: List[Dict[str, Any]]) -> None:
    if not traces:
        console.print("[dim]No trace data found. Run some queries first.[/dim]")
        return

    n = len(traces)

    # --- Tool failures ---
    tool_stats = _tool_stats(traces)

    # --- Knowledge gaps (low similarity) ---
    low_sim = [t for t in traces if (t.get("similarity_score") or 0) < 0.30]

    # --- Hop limit hits ---
    hop_hits = [t for t in traces if t.get("hop_limit_hit")]

    # --- Worst query type (tools_only runs that never resolved) ---
    worst: Counter = Counter()
    for t in traces:
        if t.get("routing_decision") == "tools_only" and t.get("hop_limit_hit"):
            # First two words of query as "type"
            label = " ".join((t.get("query") or "").split()[:3])
            worst[label] += 1

    # --- Human-labeled failures ---
    human_failures = [t for t in traces if t.get("outcome") == "n"]

    # Print ---
    console.rule("[bold red]FAILURE REPORT[/bold red]")
    console.print(f"[dim]Analyzed {n} runs[/dim]\n")

    # Tool failures table
    table = Table(title="Tool Failure Rates", show_lines=True)
    table.add_column("Tool", style="cyan")
    table.add_column("Calls", justify="right")
    table.add_column("Failed", justify="right")
    table.add_column("Fail %", justify="right")
    for tool, s in sorted(tool_stats.items()):
        pct = (s["failed"] / s["total"] * 100) if s["total"] else 0
        color = "red" if pct > 50 else "yellow" if pct > 25 else "green"
        table.add_row(
            tool,
            str(s["total"]),
            str(s["failed"]),
            f"[{color}]{pct:.0f}%[/{color}]",
        )
    if tool_stats:
        console.print(table)
    else:
        console.print("[dim]No tool calls recorded yet.[/dim]")

    # Gaps / hop hits
    console.print(
        f"\n[bold]Knowledge gaps[/bold] (similarity < 0.30):  "
        f"[red]{len(low_sim)}[/red] / {n} runs"
    )
    console.print(
        f"[bold]Hop-limit exhausted[/bold] (no resolution):  "
        f"[red]{len(hop_hits)}[/red] / {n} runs"
    )
    console.print(
        f"[bold]Human-labeled failures[/bold]:               "
        f"[red]{len(human_failures)}[/red] / {n} runs"
    )

    if worst:
        top = worst.most_common(1)[0]
        console.print(f"\n[bold]Worst unresolved query pattern[/bold]: \"{top[0]}\" ({top[1]} hits)")

    console.print()

def get_failure_report_data(traces: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Non-printing version of failure report for MCP/API use."""
    if not traces:
        return {"total_runs": 0, "success_rate": 0.0, "tool_stats": {}}

    n = len(traces)
    tool_stats = _tool_stats(traces)
    low_sim = [t for t in traces if (t.get("similarity_score") or 0) < 0.30]
    hop_hits = [t for t in traces if t.get("hop_limit_hit")]
    human_failures = [t for t in traces if t.get("outcome") == "n"]
    human_successes = [t for t in traces if t.get("outcome") == "y"]
    
    total_rated = len(human_failures) + len(human_successes)
    success_rate = (len(human_successes) / total_rated) if total_rated > 0 else 1.0

    return {
        "total_runs": n,
        "success_rate": success_rate,
        "tool_stats": {tool: {"total": s["total"], "success": s["total"] - s["failed"]} for tool, s in tool_stats.items()},
        "knowledge_gaps": len(low_sim),
        "hop_limit_hits": len(hop_hits),
        "human_failures": len(human_failures)
    }


# ─── Feature 4: Trace diff view ───────────────────────────────────────────────
def _root_cause_analysis(run_a: dict, run_b: dict) -> str:
    """Rule-based diagnosis of WHY two runs differed. No LLM call."""
    insights = []

    sim_a = run_a.get("similarity_score") or 0
    sim_b = run_b.get("similarity_score") or 0
    hops_a = len(run_a.get("hops", []))
    hops_b = len(run_b.get("hops", []))
    outcome_a = run_a.get("outcome")
    outcome_b = run_b.get("outcome")
    routing_a = run_a.get("routing_decision")
    routing_b = run_b.get("routing_decision")

    # Similarity delta
    if abs(sim_a - sim_b) > 0.3:
        higher = "Run A" if sim_a > sim_b else "Run B"
        lower = "Run B" if sim_a > sim_b else "Run A"
        insights.append(
            f"KNOWLEDGE GAP: {lower} had low memory similarity ({min(sim_a, sim_b):.2f}) "
            f"vs {higher} ({max(sim_a, sim_b):.2f}). "
            f"Root cause: insufficient indexed context at time of {lower}."
        )

    # Routing difference
    if routing_a != routing_b:
        insights.append(
            f"ROUTING SHIFT: {routing_a} → {routing_b}. "
            f"Agent switched strategy between runs, indicating memory state changed."
        )

    # Tool failures per run
    for run, label in [(run_a, "Run A"), (run_b, "Run B")]:
        failed = [h for h in run.get("hops", []) if h.get("status") in ("error", "empty")]
        if failed:
            tools = [h.get("tool", "unknown") for h in failed]
            insights.append(
                f"TOOL FAILURE in {label}: {', '.join(tools)} returned no results. "
                f"Agent had to fall back or synthesize without grounded data."
            )

    # Outcome flip
    if outcome_a == "y" and outcome_b == "n":
        insights.append(
            "REGRESSION DETECTED: Run A succeeded but Run B failed on a similar query. "
            "Possible cause: memory state degraded or tool reliability dropped."
        )
    elif outcome_a == "n" and outcome_b == "y":
        insights.append(
            "FIX VERIFIED: Run A failed, Run B succeeded on a similar query. "
            "The intervention between runs demonstrably improved agent performance."
        )

    # Hop count difference
    if abs(hops_a - hops_b) >= 2:
        more = "Run A" if hops_a > hops_b else "Run B"
        insights.append(
            f"EFFICIENCY DELTA: {more} required {abs(hops_a - hops_b)} more tool hops. "
            f"Higher hop count indicates the agent struggled to find grounded context."
        )

    if not insights:
        insights.append("Runs are structurally similar. No significant behavioral difference detected.")

    return "\n".join(f"  • {i}" for i in insights)


def print_trace_diff(t1: Dict[str, Any], t2: Dict[str, Any]) -> None:
    console.rule("[bold blue]TRACE COMPARISON[/bold blue]")

    rows = [
        ("Run ID",            t1["run_id"][:8] + "…", t2["run_id"][:8] + "…"),
        ("Timestamp",         t1.get("timestamp", "—"), t2.get("timestamp", "—")),
        ("Query",             (t1.get("query") or "")[:60], (t2.get("query") or "")[:60]),
        ("Similarity",        str(round(t1.get("similarity_score") or 0, 3)),
                              str(round(t2.get("similarity_score") or 0, 3))),
        ("Routing",           t1.get("routing_decision", "—"), t2.get("routing_decision", "—")),
        ("Hops executed",     str(len(t1.get("hops", []))), str(len(t2.get("hops", [])))),
        ("Hop limit hit",     "YES" if t1.get("hop_limit_hit") else "no",
                              "YES" if t2.get("hop_limit_hit") else "no"),
        ("Human outcome",     t1.get("outcome") or "unrated", t2.get("outcome") or "unrated"),
    ]

    table = Table(show_lines=True)
    table.add_column("Field",   style="bold")
    table.add_column("Run A",   style="cyan")
    table.add_column("Run B",   style="magenta")
    for r in rows:
        table.add_row(*r)
    console.print(table)

    console.print("\n[bold yellow]⚡ Root Cause Analysis[/bold yellow]")
    console.print(_root_cause_analysis(t1, t2))
    console.print()


# ─── Feature 6: Anomaly alerts ────────────────────────────────────────────────
def print_anomaly_alerts(traces: List[Dict[str, Any]]) -> None:
    recent = traces[:RECENT_WINDOW]
    if not recent:
        console.print("[dim]Not enough data to evaluate alerts.[/dim]")
        return

    fired = False

    # Tool failure alert
    tool_stats = _tool_stats(recent)
    for tool, s in tool_stats.items():
        if s["total"] >= 3:
            rate = s["failed"] / s["total"]
            if rate > ALERT_TOOL_FAIL_RATE:
                fired = True
                console.print(
                    Panel(
                        f"[bold yellow]⚠️  ALERT:[/bold yellow] [cyan]{tool}[/cyan] failed "
                        f"[red]{s['failed']}/{s['total']}[/red] recent calls "
                        f"([red]{rate*100:.0f}%[/red])\n"
                        f"Possible cause: API rate limit or token expiry.\n"
                        f"Action: Verify your GITHUB_TOKEN is valid and not rate-limited.",
                        border_style="yellow",
                    )
                )

    # Low average similarity alert
    scores = [t.get("similarity_score") or 0 for t in recent if t.get("similarity_score") is not None]
    if scores:
        avg = sum(scores) / len(scores)
        if avg < ALERT_LOW_SIMILARITY:
            fired = True
            console.print(
                Panel(
                    f"[bold yellow]⚠️  ALERT:[/bold yellow] Average similarity score is "
                    f"[red]{avg:.3f}[/red] (threshold: {ALERT_LOW_SIMILARITY})\n"
                    f"Possible cause: Knowledge base hasn't been refreshed recently.\n"
                    f"Action: Run [bold]index prs <repo> 50[/bold] to refresh memory.",
                    border_style="yellow",
                )
            )

    # Hop-limit rate alert
    hop_hits = sum(1 for t in recent if t.get("hop_limit_hit"))
    if recent:
        rate = hop_hits / len(recent)
        if rate > ALERT_HOP_LIMIT_RATE:
            fired = True
            console.print(
                Panel(
                    f"[bold yellow]⚠️  ALERT:[/bold yellow] "
                    f"[red]{hop_hits}/{len(recent)}[/red] recent runs exhausted all tool hops "
                    f"without resolving the query ([red]{rate*100:.0f}%[/red])\n"
                    f"Possible cause: Queries are outside the knowledge base scope.\n"
                    f"Action: Index more relevant repos or broaden search terms.",
                    border_style="yellow",
                )
            )

    if not fired:
        console.print(Panel("[green]✅ All systems nominal. No anomalies detected.[/green]", border_style="green"))
def get_anomaly_alerts_data(traces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Returns a list of active alerts as dictionaries."""
    recent = traces[:RECENT_WINDOW]
    alerts = []
    
    if not recent:
        return alerts

    # Tool failure alert
    tool_stats = _tool_stats(recent)
    for tool, s in tool_stats.items():
        if s["total"] >= 3:
            rate = s["failed"] / s["total"]
            if rate > ALERT_TOOL_FAIL_RATE:
                alerts.append({
                    "type": "tool_failure",
                    "tool": tool,
                    "message": f"Tool '{tool}' is failing {rate*100:.0f}% of calls.",
                    "severity": "high"
                })

    # Low similarity
    scores = [t.get("similarity_score") or 0 for t in recent if t.get("similarity_score") is not None]
    if scores:
        avg = sum(scores) / len(scores)
        if avg < ALERT_LOW_SIMILARITY:
            alerts.append({
                "type": "low_similarity",
                "message": f"Average similarity ({avg:.3f}) is below threshold.",
                "severity": "medium"
            })

    # Hop limit
    hop_hits = sum(1 for t in recent if t.get("hop_limit_hit"))
    rate = hop_hits / len(recent)
    if rate > ALERT_HOP_LIMIT_RATE:
        alerts.append({
            "type": "hop_limit_exhausted",
            "message": f"{rate*100:.0f}% of runs are hitting the hop limit.",
            "severity": "high"
        })

    return alerts


# Public alias so external modules can import without using private name
root_cause_analysis = _root_cause_analysis

async def deep_failure_analysis(traces: List[Dict[str, Any]]) -> str:
    """
    LLM-powered analysis of multiple failed runs.
    Synthesizes common failure patterns and suggests solutions/StackOverflow queries.
    """
    if not traces:
        return "No traces provided for deep analysis."

    # Prepare context for LLM
    context_blocks = []
    for t in traces:
        hops_summary = [f"{h.get('tool')}({h.get('status')})" for h in t.get("hops", [])]
        context_blocks.append(
            f"Run ID: {t['run_id']}\n"
            f"Query: {t.get('query')}\n"
            f"Decision: {t.get('routing_decision')}\n"
            f"Hops: {' -> '.join(hops_summary)}\n"
            f"Final Answer/Error: {t.get('final_answer')}\n"
        )

    prompt = [
        {"role": "system", "content": (
            "You are a Senior DevOps SRE. You are analyzing a set of failed agent runs. "
            "Your goal is to provide a 'proper view' of why these failures are happening. "
            "1. Summarize the common failure pattern across these runs.\n"
            "2. Identify if it is a knowledge gap, a tool failure, or a reasoning error.\n"
            "3. Suggest 3 specific StackOverflow/StackExchange search queries that might help find a solution.\n"
            "Format the output with clear headers: [SUMMARY], [ROOT CAUSE], [SUGGESTED SEARCHES]."
        )},
        {"role": "user", "content": f"Analyze these {len(traces)} runs:\n\n" + "\n---\n".join(context_blocks)},
    ]

    try:
        llm = _get_llm()
        return await llm.simple_chat(prompt)
    except Exception as e:
        return f"Deep analysis failed: {str(e)}"

async def generate_dynamic_fix(run: Dict[str, Any], root_cause: str) -> Dict[str, Any]:
    """
    LLM-powered single-run fix generator.
    Returns a structured fix proposal: {fix_type, fix_action, fix_params, explanation}.
    """
    llm = _get_llm()
    
    # Identify the target repo from query context
    query = (run.get("query") or "").lower()
    repo = "django/django" # default
    if "fastapi" in query: repo = "tiangolo/fastapi"
    elif "transformers" in query: repo = "huggingface/transformers"

    # Build a detailed history of what happened
    hops = run.get("hops", [])
    history = []
    for i, h in enumerate(hops, 1):
        history.append(f"Hop {i}: {h.get('tool')} -> Status: {h.get('status')}")
    
    history_str = "\n".join(history) if history else "No tool hops executed."

    prompt = [
        {"role": "system", "content": (
            "You are an Autonomous Self-Healing Agent. Given a failed execution trace, its history, and its root cause analysis, "
            "you must propose a specific, executable fix.\n"
            "Supported Fix Types:\n"
            "- index_more_data: If the agent lacks context (params: {tool: 'index_repo_prs', repo: string, count: int})\n"
            "- tool_config: If a specific tool is failing (params: {tool: string, action: 'retry'|'check_auth'})\n"
            "- manual_review: If you cannot automate the fix.\n\n"
            "Output EXACTLY a JSON block with: fix_type, fix_action, fix_params, explanation."
        )},
        {"role": "user", "content": (
            f"Run ID: {run['run_id']}\n"
            f"Query: {run.get('query')}\n"
            f"History:\n{history_str}\n"
            f"Root Cause: {root_cause}"
        )},
    ]
    
    try:
        import json
        raw = await llm.simple_chat(prompt)
        # Clean potential markdown
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        return {
            "fix_type": "manual_review",
            "fix_action": f"Dynamic fix generation failed: {str(e)}",
            "fix_params": {},
            "explanation": "Fall back to manual review due to LLM error."
        }
