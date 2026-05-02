"""
Observability module using Rich for NASA-dashboard terminal output.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from typing import Any, Dict

import sys

import sys

# Redirect console to stderr to prevent stdout pollution in MCP mode
# while maintaining rich output for CLI users.
console = Console(file=sys.stderr)


def log_triage(score: float, threshold: float, decision: str) -> None:
    """Log the triage decision with color coding."""
    routing = {
        "memory_only": {"label": "MEMORY-ONLY", "color": "green", "emoji": "🧠"},
        "hybrid": {"label": "HYBRID", "color": "yellow", "emoji": "🧩"},
        "tools_only": {"label": "TOOLS-FIRST", "color": "cyan", "emoji": "🔧"},
    }
    entry = routing.get(decision, {"label": decision.upper(), "color": "yellow", "emoji": "🔧"})
    text = Text()
    text.append(f"{entry['emoji']} [TRIAGE] ", style=f"bold {entry['color']}")
    text.append(f"Similarity Score: {score:.3f}", style="white")
    text.append(f" / Threshold: {threshold}", style="white")
    text.append(f" → Decision: {entry['label']}", style=f"bold {entry['color']}")
    console.print(
        Panel(text, border_style=entry["color"], title="Semantic Router", title_align="left")
    )


def log_tool_call(tool_name: str, arguments: Dict[str, Any], result_status: str) -> None:
    """Log a tool execution step."""
    color = "green" if result_status == "success" else "red" if result_status == "error" else "yellow"
    emoji = "✅" if result_status == "success" else "❌" if result_status == "error" else "⚠️"
    text = Text()
    text.append(f"{emoji} [TOOL] ", style=f"bold {color}")
    text.append(f"{tool_name}", style=f"bold cyan")
    text.append(f" | Status: {result_status}", style="white")
    console.print(Panel(text, border_style=color, title_align="left"))


def log_memory_update(issue: str, fix: str, row_id: int) -> None:
    """Log when a new fact is persisted to SQLite."""
    text = Text()
    text.append("💾 [MEMORY] ", style="bold magenta")
    text.append(f"Saved JSON memory (id={row_id})", style="white")
    console.print(
        Panel(text, border_style="magenta", title="Memory Evolution", title_align="left")
    )
    console.print(f"   Issue: {issue[:80]}...", style="dim")
    console.print(f"   Fix: {fix[:80]}...", style="dim")


def log_hop(hop_num: int, max_hops: int) -> None:
    """Log the current tool hop counter."""
    console.print(
        f"[dim]→ Tool Hop {hop_num}/{max_hops}[/dim]",
        style="cyan"
    )


def log_error(message: str) -> None:
    """Log an error with red styling."""
    console.print(Panel(f"❌ {message}", border_style="red", title="Error", title_align="left"))


def log_info(message: str) -> None:
    """Log general info."""
    console.print(Panel(f"ℹ️  {message}", border_style="blue", title="Info", title_align="left"))


def log_index_step(item_type: str, item_num: int, title: str) -> None:
    """Log an item being indexed in a compact format."""
    console.print(f"   [bold cyan]•[/bold cyan] [dim]{item_type} #{item_num}:[/dim] {title[:60]}...", style="white")


def print_banner() -> None:
    """Print the Observable Agent Control Panel startup banner."""
    banner = r"""
     ██████  ██████  ████████  █████   ██████ ██      ██      ██████  ██████ 
     ██   ██ ██   ██    ██    ██   ██ ██      ██      ██      ██   ██ ██     
     ██   ██ ██████     ██    ███████ ██      ██      ██      ██████  ██████ 
     ██   ██ ██         ██    ██   ██ ██      ██      ██      ██   ██ ██     
     ██████  ██         ██    ██   ██  ██████ ███████ ███████ ██   ██ ██████ 
    """
    console.print(Panel(banner, border_style="bright_cyan", title="Observable Agent Control Panel v1.0", subtitle="Ready"))


def print_response(content: str) -> None:
    """Pretty-print the assistant's final response."""
    console.print(Panel(content, border_style="green", title="🤖 Assistant", title_align="left"))
