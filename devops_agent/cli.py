"""
Rich-based CLI client for standalone DevOps Agent MCP demos.
Provides a high-fidelity interactive environment for debugging the agent's logic.
Now supports ASYNC execution.
"""

import os
import sys
import time
import json
import asyncio
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

# Path resolution
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.text import Text
from rich.box import ROUNDED

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML

# Local modules
from devops_agent.core.llm_client import LLMClient
from devops_agent.core.orchestrator import Orchestrator
from devops_agent.memory.long_term import LongTermMemory
from observable_agent_panel.core.observability import (
    print_banner,
    print_response,
    log_error,
    log_info,
    log_success,
)
from observable_agent_panel.core.trace_db import trace_db
from observable_agent_panel.core.analyzer import (
    print_failure_report,
    print_trace_diff,
    print_anomaly_alerts,
    root_cause_analysis
)
from devops_agent.tools.github_tools import get_current_repo, set_current_repo, get_stored_repos

load_dotenv()
console = Console()

# --- Custom Completer for CLI ---
class DevOpsCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lower()
        
        # Repository completions
        if text.startswith("repo ") or text.startswith("index prs ") or text.startswith("index issues "):
            repos = get_stored_repos()
            word = document.get_word_before_cursor()
            for r in repos:
                if word.lower() in r.lower():
                    yield Completion(r, start_position=-len(word))
        
        # Command completions
        commands = ["help", "exit", "clear", "analyze", "traces", "explain", "compare", "heal", "alerts", "repo", "index prs", "index issues"]
        if not " " in text:
            word = document.get_word_before_cursor()
            for cmd in commands:
                if cmd.startswith(word.lower()):
                    yield Completion(cmd, start_position=-len(word))

# --- Observability Commands ---

def cmd_analyze():
    """Display the recent tool performance and failure report."""
    traces = trace_db.get_recent_traces(50)
    print_failure_report(traces)

def cmd_alerts():
    """Check for active system anomalies."""
    traces = trace_db.get_recent_traces(50)
    print_anomaly_alerts(traces)

def cmd_traces(count: int = 20):
    """List recent agent run IDs and metadata."""
    traces = trace_db.get_recent_traces(count)
    if not traces:
        console.print("[dim]No traces recorded in this session yet.[/dim]")
        return

    table = Table(title=f"Recent {len(traces)} Agent Runs", box=ROUNDED)
    table.add_column("Run ID", style="cyan")
    table.add_column("Decision", style="bold")
    table.add_column("Sim", style="green")
    table.add_column("Hops", style="magenta")
    table.add_column("Outcome", style="yellow")
    table.add_column("Query (truncated)", style="white")

    for t in traces:
        score = t.get("similarity_score")
        score_str = f"{score:.3f}" if score is not None else "—"
        outcome = t.get("outcome") or "unrated"
        
        # Highlight hop limit hits
        hop_limit_hit = t.get("hop_limit_hit", False)
        hop_count = str(len(t.get("hops", [])))
        if hop_limit_hit:
            hop_count = f"[red]{hop_count}![/red]"
            
        table.add_row(
            t["run_id"][:8],
            t.get("routing_decision", "?"),
            score_str,
            hop_count,
            outcome,
            (t.get("query") or "")[:50] + "..."
        )
    console.print(table)

def cmd_explain(run_id_prefix: str):
    """Fetch and display the plain-English explanation for a specific run."""
    t = trace_db.get_trace(run_id_prefix)
    if not t:
        # Try prefix matching
        recent = trace_db.get_recent_traces(100)
        matches = [r for r in recent if r["run_id"].startswith(run_id_prefix)]
        if not matches:
            console.print(f"[red]No trace found for run_id starting with '{run_id_prefix}'[/red]")
            return
        t = matches[0]

    console.print(Panel(
        Markdown(t.get("explanation") or "_No explanation generated for this run._"),
        title=f"Agent Reasoning Summary — {t['run_id'][:8]}",
        border_style="blue",
        padding=(1, 2)
    ))

def cmd_compare(id1: str, id2: str):
    """Compare two traces and show diff."""
    def _resolve(rid):
        t = trace_db.get_trace(rid)
        if not t:
            matches = [r for r in trace_db.get_recent_traces(100) if r["run_id"].startswith(rid)]
            return matches[0] if matches else None
        return t
    
    t1, t2 = _resolve(id1), _resolve(id2)
    if t1 and t2:
        print_trace_diff(t1, t2)
    else:
        console.print("[red]One or both Trace IDs could not be found.[/red]")

async def cmd_self_heal(orchestrator: Orchestrator):
    """
    Experimental: Interactive Self-Healing Loop. (Async)
    1. Scan for failures
    2. Analyze root cause vs successes
    3. Generate tool-based fix
    4. Apply & Verify
    """
    from observable_agent_panel.core.self_healing import get_failure_candidates, propose_fix, verify_fix
    
    console.print(Panel("[bold magenta]Step 1: Finding Failure Candidates[/bold magenta]", border_style="magenta"))
    failures, total = get_failure_candidates(limit=3)
    
    if not failures:
        console.print("[green]No high-priority failures detected. System is healthy.[/green]")
        return
    
    # Selection Table
    table = Table(title="Failure Candidates for Healing", box=ROUNDED)
    table.add_column("#", style="dim")
    table.add_column("Run ID", style="cyan")
    table.add_column("Query", style="white")
    table.add_column("Failed Tools", style="red")
    
    for i, f in enumerate(failures, 1):
        hops = f.get("hops", [])
        failed_tools = list(set([h["tool"] for h in hops if h["status"] in ("error", "empty")]))
        table.add_row(str(i), f["run_id"][:8], f["query"][:60], ", ".join(failed_tools))
    
    console.print(table)
    choice = Prompt.ask("\nSelect a candidate to heal (or 'q' to cancel)", default="1")
    if choice.lower() == 'q': return
    
    try:
        target = failures[int(choice)-1]
    except (ValueError, IndexError):
        console.print("[red]Invalid selection.[/red]")
        return

    # Step 2: Diagnose
    console.print(Panel(f"Step 2: Diagnosing Root Cause for '{target['run_id'][:8]}'", border_style="magenta"))
    successes = [t for t in trace_db.get_recent_traces(50) if t.get("outcome") == "y"]
    
    if not successes:
        root_cause = "Insufficient success history to compare. Analyzing trace in isolation..."
    else:
        # Compare vs latest success
        root_cause = root_cause_analysis(target, successes[0])
        
    console.print(f"[yellow]Root Cause Analysis:[/yellow]\n{root_cause}\n")
    
    # Step 3: Propose
    console.print(Panel("Step 3: Generating Fix Proposal", border_style="magenta"))
    fix_proposal = propose_fix(target["run_id"], root_cause)
    
    console.print(f"[bold green]Proposed Action:[/bold green] {fix_proposal['fix_action']}")
    console.print(f"[dim]Rationale: {fix_proposal['fix_type']}[/dim]")
    console.print(f"Parameters: [cyan]{fix_proposal['fix_params']}[/cyan]\n")
    
    if Prompt.ask("Apply this fix automatically?", choices=["y", "n"], default="n") != "y":
        return
        
    # Step 4: Apply
    console.print(Panel("Step 4: Applying Fix (Executing Tool)", border_style="magenta"))
    params = fix_proposal["fix_params"]
    tool_to_run = params.get("tool")
    
    with console.status(f"[bold blue]Running {tool_to_run}...[/bold blue]"):
        if tool_to_run == "index_repo_prs":
            res = await orchestrator.index_repo_prs(params["repo"], count=params["count"])
        elif tool_to_run == "index_repo_issues":
            res = await orchestrator.index_repo_issues(params["repo"], count=params["count"])
        else:
            console.print(f"[red]Error: Auto-apply for tool '{tool_to_run}' not implemented in CLI.[/red]")
            return
            
    if res.get("status") == "success":
        console.print(f"[bold green]Fix Applied Successfully![/bold green] {res.get('message')}")
    else:
        console.print(f"[bold red]Fix Application Failed:[/bold red] {res.get('message')}")
        return
        
    # Step 5: Verify
    console.print(Panel("Step 5: Verifying Resolution (Re-running Query)", border_style="magenta"))
    with console.status("[bold blue]Agent is re-processing the original query...[/bold blue]"):
        await orchestrator.process_query(target["query"])
        new_run_id = trace_db.last_run_id
    
    # Run the verification logic
    ver_res = verify_fix(target["run_id"], new_run_id)
    
    if ver_res["verdict"] == "FIXED":
        console.print("\n[bold green]✅ VERIFICATION SUCCESSFUL: The agent now handles this query correctly.[/bold green]")
    else:
        console.print("\n[bold red]❌ VERIFICATION FAILED: The agent still encounters issues.[/bold red]")
        console.print(f"[dim]Reason: {ver_res['fix_verified']}[/dim]")


async def main_async() -> None:
    """Async entry point for the CLI."""
    # Process potential CLI flags first (non-interactive)
    args = sys.argv[1:]
    if "--analyze" in args:
        cmd_analyze()
        return
    
    if "--self-heal" in args:
        db_path = os.path.join(ROOT_DIR, "data", "memory.db")
        memory = LongTermMemory(db_path=db_path)
        orchestrator = Orchestrator(LLMClient(), memory)
        await cmd_self_heal(orchestrator)
        return

    # Normal Interactive Session
    print_banner()
    
    # Initialize Core
    try:
        db_path = os.path.join(ROOT_DIR, "data", "memory.db")
        memory = LongTermMemory(db_path=db_path)
        llm = LLMClient()
        orchestrator = Orchestrator(llm, memory)
        log_success("Agent Core Initialized Successfully.")
    except Exception as e:
        log_error(f"Failed to initialize agent: {e}")
        return

    # Check for current repo
    current_repo = get_current_repo()
    if not current_repo:
        console.print("[yellow]No default repository set. Use 'repo <org/name>' to target a codebase.[/yellow]")
    else:
        console.print(f"Targeting Repository: [bold cyan]{current_repo}[/bold cyan]")

    # Setup Prompt Session
    style = Style.from_dict({
        'prompt': 'ansicyan bold',
    })
    session = PromptSession(completer=DevOpsCompleter(), style=style)

    console.print("\n[bold]Observable Agent Control Panel — Interactive Session[/bold]")
    console.print("Type [cyan]help[/cyan] for available commands or [cyan]exit[/cyan] to quit.\n")

    while True:
        try:
            user_input = await session.prompt_async(HTML("<b><ansicyan>You</ansicyan></b>: "))
            user_input = user_input.strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        clean_input = user_input.lower()

        # Handle Commands
        if clean_input in ("exit", "quit", "q"):
            break
        
        if clean_input == "help":
            help_table = Table(title="Observable Agent Command Reference", box=ROUNDED, show_header=True, header_style="bold magenta")
            help_table.add_column("Exact Command", style="cyan", no_wrap=True)
            help_table.add_column("Type", style="dim")
            help_table.add_column("Description", style="white")
            
            # Startup Flags
            help_table.add_section()
            help_table.add_row("--mode cli", "Shell Flag", "Start the interactive Control Panel.")
            help_table.add_row("--mode server", "Shell Flag", "Start the MCP stdio server.")
            help_table.add_row("--analyze", "Shell Flag", "Run analysis and exit.")
            help_table.add_row("--self-heal", "Shell Flag", "Run interactive healing and exit.")
            
            # Interactive Commands
            help_table.add_section()
            help_table.add_row("repo <org/repo>", "Interactive", "Set the target repository.")
            help_table.add_row("index prs <repo> [n]", "Interactive", "Index latest PRs into memory.")
            help_table.add_row("index issues <repo> [n]", "Interactive", "Index latest issues into memory.")
            help_table.add_row("analyze", "Interactive", "View performance and failures.")
            help_table.add_row("traces", "Interactive", "List recent run metadata.")
            help_table.add_row("explain <id>", "Interactive", "Show agent reasoning summary.")
            help_table.add_row("compare <id1> <id2>", "Interactive", "Analyze diff between two runs.")
            help_table.add_row("heal", "Interactive", "Launch self-healing wizard.")
            help_table.add_row("alerts", "Interactive", "Check for system anomalies.")
            help_table.add_row("clear", "Interactive", "Clear the terminal screen.")
            help_table.add_row("help", "Interactive", "Show this reference table.")
            help_table.add_row("exit / quit / q", "Interactive", "Exit the Control Panel.")
            
            console.print(help_table)
            console.print("\n[dim]Note: Shell flags must be passed when starting the agent via main.py (e.g., [cyan]python devops_agent/main.py --analyze[/cyan]).[/dim]")
            continue

        if clean_input == "clear":
            console.clear()
            continue

        if clean_input == "analyze":
            cmd_analyze()
            continue
            
        if clean_input == "alerts":
            cmd_alerts()
            continue

        if clean_input == "traces":
            cmd_traces()
            continue
            
        if clean_input == "heal":
            await cmd_self_heal(orchestrator)
            continue

        if clean_input.startswith("explain "):
            cmd_explain(clean_input.split()[1])
            continue

        if clean_input.startswith("compare "):
            parts = clean_input.split()
            if len(parts) >= 3:
                cmd_compare(parts[1], parts[2])
            else:
                console.print("[red]Usage: compare <id1> <id2>[/red]")
            continue

        if clean_input.startswith("repo "):
            repo_name = user_input.split()[1]
            set_current_repo(repo_name)
            log_info(f"Target repository updated to: [bold]{repo_name}[/bold]")
            continue

        if clean_input.startswith("index prs "):
            parts = user_input.split()
            if len(parts) >= 3:
                repo_name = parts[2]
                count = int(parts[3]) if len(parts) > 3 else 10
                with console.status(f"[bold blue]Indexing PRs from {repo_name}...[/bold blue]"):
                    res = await orchestrator.index_repo_prs(repo_name, count=count)
                if res["status"] == "success":
                    log_success(res["message"])
                else:
                    log_error(res["message"])
            else:
                console.print("[red]Usage: index prs <org/repo> [count][/red]")
            continue

        if clean_input.startswith("index issues "):
            parts = user_input.split()
            if len(parts) >= 3:
                repo_name = parts[2]
                count = int(parts[3]) if len(parts) > 3 else 10
                with console.status(f"[bold blue]Indexing issues from {repo_name}...[/bold blue]"):
                    res = await orchestrator.index_repo_issues(repo_name, count=count)
                if res["status"] == "success":
                    log_success(res["message"])
                else:
                    log_error(res["message"])
            else:
                console.print("[red]Usage: index issues <org/repo> [count][/red]")
            continue

        # Handle Regular Queries
        from observable_agent_panel.core.observability import set_active_status, update_status
        status = console.status("[bold cyan]ANALYZING_INTENT...[/bold cyan]", spinner="arc")
        status.start()
        set_active_status(status)
        
        try:
            # Start clock
            start_time = time.monotonic()
            
            # Call Async Orchestrator
            response_text = await orchestrator.process_query(user_input)
            
            duration = time.monotonic() - start_time
            
            # Stop status before printing final response
            status.stop()
            
            # Display Results
            from observable_agent_panel.core.observability import print_response
            print_response(response_text, source=orchestrator.last_run_source)
            
            # Feedback loop
            console.print(f"[dim]RUN_ID: {trace_db.last_run_id[:8]} | LATENCY: {duration:.2f}s[/dim]")
            
            # Simple interactive rating
            rating = Prompt.ask("\nRate this answer?", choices=["y", "n", "s"], default="s")
            if rating != "s":
                trace_db.set_outcome(rating)
                log_info(f"Answer rated: [bold]{'Success' if rating == 'y' else 'Failure'}[/bold]")
            
        except Exception as e:
            status.stop()
            set_active_status(None)
            log_error(f"MISSION_FAILURE: {str(e)}")
        finally:
            set_active_status(None)

    console.print("\n[bold blue]Session Ended.[/bold blue] Goodbye!")

def main():
    """Main entry point for the CLI."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        # Silently exit on Ctrl+C
        pass

if __name__ == "__main__":
    main()
