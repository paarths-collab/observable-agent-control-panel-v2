"""
Rich-based CLI client for standalone DevOps Agent MCP demos.

New observability commands:
  python cli.py --analyze        # Feature 2: failure report
  python cli.py --alerts         # Feature 6: anomaly alerts
  python cli.py --traces [N]     # list recent N trace run IDs
  python cli.py --explain <id>   # Feature 5: show explanation for a run
  python cli.py --compare-runs <id1> <id2>  # Feature 4: diff two runs
"""

import os
import sys
from typing import List, Optional
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.markdown import Markdown
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML

from devops_agent.core.llm_client import LLMClient
from devops_agent.core.orchestrator import Orchestrator
from devops_agent.memory.long_term import LongTermMemory
from observable_agent_panel.core.observability import print_banner, print_response, log_error, log_info
from observable_agent_panel.core.trace_db import trace_db
from observable_agent_panel.core.analyzer import print_failure_report, print_trace_diff, print_anomaly_alerts
from devops_agent.tools.github_tools import get_current_repo, set_current_repo, get_stored_repos

load_dotenv()
console = Console()


class RepoCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lower()
        if text.startswith("repo ") or "index" in text:
            repos = get_stored_repos()
            word = document.get_word_before_cursor()
            for r in repos:
                if word.lower() in r.lower():
                    yield Completion(r, start_position=-len(word))


# ─── Observability CLI entry-points ──────────────────────────────────────────

def cmd_analyze():
    traces = trace_db.get_recent_traces(50)
    print_failure_report(traces)


def cmd_alerts():
    traces = trace_db.get_recent_traces(50)
    print_anomaly_alerts(traces)


def cmd_traces(n: int = 20):
    traces = trace_db.get_recent_traces(n)
    if not traces:
        console.print("[dim]No traces recorded yet.[/dim]")
        return
    console.print(f"\n[bold blue]Recent {len(traces)} Traces[/bold blue]\n")
    for t in traces:
        score = t.get("similarity_score")
        score_str = f"{score:.3f}" if score is not None else "—"
        outcome = t.get("outcome") or "unrated"
        hop_hit = " [red][HOP LIMIT][/red]" if t.get("hop_limit_hit") else ""
        console.print(
            f"[dim]{t['timestamp'][:19]}[/dim]  "
            f"[cyan]{t['run_id']}[/cyan]  "
            f"[bold]{t.get('routing_decision', '?'):12}[/bold]  "
            f"sim={score_str}  "
            f"hops={len(t.get('hops', []))}  "
            f"outcome={outcome}{hop_hit}\n"
            f"  [dim]↳ {(t.get('query') or '')[:80]}[/dim]"
        )
    console.print()


def cmd_explain(run_id: str):
    t = trace_db.get_trace(run_id)
    if not t:
        # Try prefix match
        recent = trace_db.get_recent_traces(100)
        matches = [r for r in recent if r["run_id"].startswith(run_id)]
        if not matches:
            console.print(f"[red]No trace found for run_id prefix '{run_id}'[/red]")
            return
        t = matches[0]
    console.print(Panel(
        Markdown(t.get("explanation") or "[dim]No explanation generated for this run.[/dim]"),
        title=f"[bold blue]Explanation — {t['run_id'][:8]}…[/bold blue]",
        border_style="blue",
    ))


def cmd_compare(id1: str, id2: str):
    def resolve(run_id: str):
        t = trace_db.get_trace(run_id)
        if not t:
            recent = trace_db.get_recent_traces(100)
            matches = [r for r in recent if r["run_id"].startswith(run_id)]
            return matches[0] if matches else None
        return t

    t1 = resolve(id1)
    t2 = resolve(id2)
    if not t1 or not t2:
        console.print("[red]One or both trace IDs not found.[/red]")
        return
    print_trace_diff(t1, t2)


def cmd_deep_analyze(run_ids: List[str]):
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
        console.print("[red]No valid trace IDs found.[/red]")
        return
        
    with console.status("[bold blue]Performing deep failure analysis...[/bold blue]"):
        report = deep_failure_analysis(traces)
        
    console.print(Panel(
        Markdown(report),
        title=f"[bold red]Deep Failure Analysis ({len(traces)} runs)[/bold red]",
        border_style="red"
    ))


def cmd_search_logs(query: str):
    results = trace_db.search_traces(query, limit=10)
    if not results:
        console.print(f"[dim]No logs found matching '{query}'.[/dim]")
        return
    
    console.print(f"\n[bold blue]Search Results for '{query}'[/bold blue]\n")
    for r in results:
        outcome = r.get("outcome") or "unrated"
        color = "green" if outcome == "y" else "red" if outcome == "n" else "dim"
        console.print(
            f"[cyan]{r['run_id'][:8]}...[/cyan]  "
            f"[dim]{r['timestamp'][:19]}[/dim]  "
            f"[{color}]outcome={outcome}[/{color}]\n"
            f"  [bold]Q:[/bold] {(r.get('query') or '')[:80]}\n"
            f"  [bold]A:[/bold] {(r.get('final_answer') or '')[:80]}\n"
        )
    console.print()


# ─── Main interactive loop ────────────────────────────────────────────────────

def main() -> None:
    # ── Handle non-interactive CLI flags ──────────────────────────────────────
    args = sys.argv[1:]
    if "--analyze" in args:
        cmd_analyze()
        return
    if "--alerts" in args:
        cmd_alerts()
        return
    if "--traces" in args:
        idx = args.index("--traces")
        n = int(args[idx + 1]) if idx + 1 < len(args) and args[idx + 1].isdigit() else 20
        cmd_traces(n)
        return
    if "--explain" in args:
        idx = args.index("--explain")
        if idx + 1 < len(args):
            cmd_explain(args[idx + 1])
        else:
            console.print("[red]Usage: python cli.py --explain <run_id>[/red]")
        return
    if "--compare-runs" in args:
        idx = args.index("--compare-runs")
        if idx + 2 < len(args):
            cmd_compare(args[idx + 1], args[idx + 2])
        else:
            console.print("[red]Usage: python cli.py --compare-runs <id1> <id2>[/red]")
        return
    if "--deep-analyze" in args:
        idx = args.index("--deep-analyze")
        ids = args[idx + 1:]
        if ids:
            cmd_deep_analyze(ids)
        else:
            console.print("[red]Usage: python cli.py --deep-analyze <id1> <id2> ...[/red]")
        return
    if "--search-logs" in args:
        idx = args.index("--search-logs")
        if idx + 1 < len(args):
            cmd_search_logs(args[idx + 1])
        else:
            console.print("[red]Usage: python cli.py --search-logs <query>[/red]")
        return

    # ── Interactive REPL ──────────────────────────────────────────────────────
    print_banner()

    if not os.getenv("GROQ_API_KEY"):
        log_error("GROQ_API_KEY environment variable is not set.")
        console.print("[yellow]Set it with: export GROQ_API_KEY='your_key_here'[/yellow]")
        sys.exit(1)

    if not os.getenv("GITHUB_TOKEN"):
        console.print("\n[bold yellow]⚠️  Warning: GITHUB_TOKEN is not set.[/bold yellow]")
        console.print("[dim]GitHub tools will be heavily rate-limited and may fail for search queries.[/dim]")
        console.print("[dim]Set it with: export GITHUB_TOKEN='your_pat_here'[/dim]\n")

    log_info("Initializing memory and orchestrator...")
    memory = LongTermMemory(db_path="data/memory.db")
    llm = LLMClient()
    orchestrator = Orchestrator(llm_client=llm, long_term=memory)

    console.print(
        Panel(
            "[bold green]Observable Agent Control Panel CLI Ready[/bold green]\n"
            f"Current Repo Context: [cyan]{get_current_repo()}[/cyan]\n"
            "Note: 'Summarize' queries now prioritize existing memory without extraction.\n"
            "Type your debugging query below. Type [bold cyan]'help'[/bold cyan] for all commands.\n"
            "Type [bold yellow]'exit'[/bold yellow] to quit.",
            title="Observable Agent Control Panel",
            border_style="green",
        )
    )

    session = PromptSession(completer=RepoCompleter())

    while True:
        try:
            user_input = session.prompt(HTML("\n<b><ansicyan>You</ansicyan></b>: ")).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n👋 Goodbye!")
            break

        if not user_input:
            continue

        # Strip accidental 'python cli.py' or 'python main.py' prefix
        if user_input.lower().startswith("python "):
            for prefix in ["python cli.py ", "python main.py ", "python "]:
                if user_input.lower().startswith(prefix):
                    user_input = user_input[len(prefix):].strip()
                    break

        if user_input.lower() in ("exit", "quit", "q"):
            console.print("👋 Goodbye!")
            break

        # ── Built-in commands ─────────────────────────────────────────────────
        if user_input.lower() == "memories":
            choice = Prompt.ask(
                "\n[bold cyan]Browse memories (g)lobally or by (r)epo?[/bold cyan]",
                choices=["g", "r"], default="g",
            )
            repo_filter = None
            if choice == "r":
                repos = get_stored_repos()
                if not repos:
                    console.print("[dim]No repositories found in database.[/dim]")
                    continue
                console.print("\n[bold blue]Available Repositories:[/bold blue]")
                for idx, r in enumerate(repos, 1):
                    console.print(f"  {idx}. {r}")
                repo_idx_str = Prompt.ask("\n[bold cyan]Select a repo number[/bold cyan]")
                try:
                    repo_idx = int(repo_idx_str) - 1
                    if 0 <= repo_idx < len(repos):
                        repo_filter = repos[repo_idx]
                    else:
                        console.print("[red]Invalid selection.[/red]")
                        continue
                except ValueError:
                    console.print("[red]Invalid number.[/red]")
                    continue
            facts = memory.list_facts(limit=100, repo_filter=repo_filter)
            if not facts:
                console.print("[dim]No memories stored yet.[/dim]")
            else:
                title = f"Saved Institutional Memories ({repo_filter or 'Global'}):"
                console.print(f"\n[bold blue]{title}[/bold blue]")
                for f in facts:
                    repo = f.get("repo_name", "Unknown")
                    console.print(
                        f"[bold cyan][ID: {f['id']}][/bold cyan] [yellow][{repo}][/yellow]\n"
                        f"  [dim]Issue:[/dim] {f['issue'][:80]}...\n"
                        f"  [dim]Fix:[/dim] {f['resolution'][:80]}...\n"
                    )
                console.print(f"\n[dim]Showing {len(facts)} items.[/dim]")
            continue

        if user_input.lower() == "help":
            console.print(
                Panel(
                    "[bold yellow]Core Commands:[/bold yellow]\n"
                    "  [cyan]memories[/cyan]               - Browse saved institutional facts\n"
                    "  [cyan]clear[/cyan]                  - Wipe all local memories\n"
                    "  [cyan]repo <owner/name>[/cyan]     - Switch repository context\n"
                    "  [cyan]repos[/cyan]                 - List indexed repositories\n"
                    "  [cyan]index <repo>[/cyan]          - Index PRs/Issues into memory\n\n"
                    "[bold yellow]Observability Commands (Copy-Pasteable Flags):[/bold yellow]\n"
                    "  [cyan]--traces [N][/cyan]         - List last N agent runs (with IDs)\n"
                    "  [cyan]--analyze[/cyan]            - Show failure report and tool stats\n"
                    "  [cyan]--alerts[/cyan]             - Run anomaly detection on recent runs\n"
                    "  [cyan]--explain <ID>[/cyan]      - Show LLM rationale for a specific run\n"
                    "  [cyan]--search-logs <query>[/cyan] - Search traces for error patterns\n"
                    "  [cyan]--compare <ID1> <ID2>[/cyan]- Side-by-side diff of two runs\n"
                    "  [cyan]--deep-analyze <IDs>[/cyan]- Multi-run LLM failure diagnosis\n\n"
                    "[bold yellow]Optimization:[/bold yellow]\n"
                    "  - 'Summarize' queries are optimized to use existing memory.\n\n"
                    "[bold yellow]System:[/bold yellow]\n"
                    "  [cyan]mcp[/cyan]                   - Show IDE integration instructions\n"
                    "  [cyan]exit[/cyan]                  - Close the Control Panel",
                    title="Control Panel Help",
                    border_style="blue",
                )
            )
            continue

        if user_input.lower() in ("traces", "--traces"):
            cmd_traces(20)
            continue
        
        if user_input.lower().startswith("traces ") or user_input.lower().startswith("--traces "):
            parts = user_input.split()
            n = 20
            if len(parts) > 1:
                try:
                    n = int(parts[1])
                except ValueError:
                    pass
            cmd_traces(n)
            continue

        if user_input.lower() in ("analyze", "--analyze"):
            cmd_analyze()
            continue

        if user_input.lower() in ("alerts", "--alerts"):
            cmd_alerts()
            continue

        if user_input.lower().startswith("compare ") or user_input.lower().startswith("--compare "):
            parts = user_input.split()
            if len(parts) < 3:
                console.print("[red]Usage: --compare <id1> <id2>[/red]")
            else:
                cmd_compare(parts[1], parts[2])
            continue

        # Strip common prefixes if user pastes full command
        if user_input.startswith("python cli.py "):
            user_input = user_input.replace("python cli.py ", "").strip()
        elif user_input.startswith("python -m devops_agent.main "):
             user_input = user_input.replace("python -m devops_agent.main ", "").strip()

        # Command: Explain
        if user_input.lower().startswith("explain ") or user_input.lower().startswith("--explain "):
            cmd_explain(user_input.split(" ", 1)[1].strip())
            continue

        # Command: Deep Analyze
        if user_input.lower().startswith("deep-analyze ") or \
           user_input.lower().startswith("--deep-analyze ") or \
           user_input.lower().startswith("--deep analyze "):
            parts = user_input.split()
            # Skip flags like --deep or analyze
            ids = [p for p in parts if not p.startswith("-") and p != "analyze"]
            cmd_deep_analyze(ids)
            continue

        if user_input.lower().startswith("search-logs ") or \
           user_input.lower().startswith("--search-logs "):
            query = user_input.split(" ", 1)[1].strip()
            cmd_search_logs(query)
            continue

        if user_input.lower() == "mcp":
            console.print(
                Panel(
                    "[bold green]How to use this MCP Server in your IDE (Cursor / Cline)[/bold green]\n\n"
                    "1. Open your IDE Settings / MCP Configuration.\n"
                    "2. Add a new MCP Server:\n"
                    "   - [bold]Type[/bold]: `command`\n"
                    "   - [bold]Name[/bold]: `observable-agent-control-panel`\n"
                    "   - [bold]Command[/bold]: `python`\n"
                    f"   - [bold]Args[/bold]: `\"{os.path.abspath('main.py')}\"`, `--mode`, `server`\n\n"
                    "3. [bold yellow]Copy-Pasteable Observability Flags:[/bold yellow]\n"
                    f"   - Analysis: `python \"{os.path.abspath('cli.py')}\" --analyze`\n"
                    f"   - Alerts:   `python \"{os.path.abspath('cli.py')}\" --alerts`\n"
                    f"   - Traces:   `python \"{os.path.abspath('cli.py')}\" --traces 10`\n\n"
                    "See [bold]docs/ide_integration.md[/bold] for full Cursor/Cline/Claude Desktop configs.",
                    border_style="magenta",
                )
            )
            continue

        if user_input.lower() == "clear":
            memory.clear_all()
            console.print("[red]All memories cleared.[/red]")
            continue

        if user_input.lower().startswith("repo "):
            new_repo = user_input.split(" ", 1)[1].strip()
            if "/" in new_repo:
                set_current_repo(new_repo)
                console.print(f"[bold green]Switched repo context to:[/bold green] {new_repo}")
            else:
                console.print("[red]Invalid format. Use owner/repo.[/red]")
            continue

        if user_input.lower().startswith("index") or user_input.lower().startswith("/index"):
            parts = user_input.split(" ")
            if parts[0].startswith("/"):
                parts[0] = parts[0][1:]
            if len(parts) < 2:
                console.print("[red]Usage: index [prs|issues] <owner/repo> [count][/red]")
                continue
            idx_type = "prs"
            repo_idx = 1
            if parts[1].lower() in ["prs", "issues"]:
                idx_type = parts[1].lower()
                repo_idx = 2
            if len(parts) <= repo_idx:
                console.print("[red]Usage: index [prs|issues] <owner/repo> [count][/red]")
                continue
            repo_to_index = parts[repo_idx].strip()
            count_to_index = 10
            if len(parts) > repo_idx + 1:
                try:
                    count_to_index = int(parts[repo_idx + 1])
                except ValueError:
                    pass
            with console.status(f"[bold yellow]Indexing {idx_type} from {repo_to_index}...[/bold yellow]"):
                if idx_type == "prs":
                    res = orchestrator.index_repo_prs(repo_to_index, count=count_to_index, storage="permanent")
                else:
                    res = orchestrator.index_repo_issues(repo_to_index, count=count_to_index, storage="permanent")
                if res.get("status") == "success":
                    console.print(f"[bold green]Successfully indexed {idx_type} from {repo_to_index}[/bold green]")
                else:
                    console.print(f"[bold red]Indexing failed: {res.get('message')}[/bold red]")
            continue

        if user_input.lower() == "repos":
            repos = get_stored_repos()
            console.print("[bold blue]Stored Repositories:[/bold blue]")
            for r in repos:
                mark = "*" if r == get_current_repo() else " "
                console.print(f"{mark} {r}")
            continue

        # ── Process query ─────────────────────────────────────────────────────
        with console.status("[bold magenta]Observable Agent Control Panel is thinking...[/bold magenta]"):
            try:
                response = orchestrator.process_query(user_input)
            except Exception as e:
                log_error(str(e))
                continue

        print_response(response)

        # ── Feature 3: Human feedback loop ────────────────────────────────────
        try:
            rating = Prompt.ask(
                "\n[dim]Was this answer helpful?[/dim]",
                choices=["y", "n", "skip"],
                default="skip",
            )
            if rating != "skip":
                trace_db.set_outcome(rating)
                if rating == "n":
                    console.print(
                        "[dim]Marked as unhelpful — logged for failure analysis.[/dim]"
                    )
        except (EOFError, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    main()
