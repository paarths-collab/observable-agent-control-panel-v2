"""
Observability module using Rich for NASA-dashboard terminal output.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.status import Status
from typing import Any, Dict, Optional
import sys

# Redirect console to stderr to prevent stdout pollution in MCP mode
# while maintaining rich output for CLI users.
console = Console(file=sys.stderr)
_current_status: Optional[Status] = None

def set_active_status(status: Optional[Status]) -> None:
    """Set the global status object for dynamic updates."""
    global _current_status
    _current_status = status

def update_status(message: str) -> None:
    """Update the active status message if one exists."""
    if _current_status:
        _current_status.update(f"[bold cyan]{message}...[/bold cyan]")


def log_triage(score: float, threshold: float, decision: str) -> None:
    """Log the triage decision with color coding."""
    routing = {
        "memory_only": {"label": "MEMORY-ONLY", "color": "green", "emoji": "🧠"},
        "hybrid": {"label": "HYBRID", "color": "yellow", "emoji": "🧩"},
        "tools_only": {"label": "TOOLS-FIRST", "color": "cyan", "emoji": "🔧"},
    }
    entry = routing.get(decision, {"label": decision.upper(), "color": "yellow", "emoji": "🔧"})
    text = Text()
    text.append(f"{entry['emoji']} [TRIAGE_SCAN] ", style=f"bold {entry['color']}")
    text.append(f"Confidence: {score:.3f}", style="white")
    text.append(f" | Target: {threshold}", style="white")
    text.append(f" → Protocol: {entry['label']}", style=f"bold {entry['color']}")
    console.print(
        Panel(text, border_style=entry["color"], title="[bold]SEMANTIC_ROUTER[/bold]", title_align="left")
    )


def log_tool_call(tool_name: str, arguments: Dict[str, Any], result_status: str) -> None:
    """Log a tool execution step."""
    color = "green" if result_status == "success" else "red" if result_status == "error" else "yellow"
    emoji = "✅" if result_status == "success" else "❌" if result_status == "error" else "⚠️"
    text = Text()
    text.append(f"   {emoji} [TOOL_EXEC] ", style=f"bold {color}")
    text.append(f"{tool_name}", style="bold cyan")
    text.append(f" → {result_status.upper()}", style=f"bold {color}")
    console.print(text)


def log_memory_update(issue: str, fix: str, row_id: int) -> None:
    """Log when a new fact is persisted to SQLite."""
    text = Text()
    text.append("💾 [MEM_COMMIT] ", style="bold magenta")
    text.append(f"ID: {row_id}", style="white")
    text.append(" | State: Persisted", style="dim")
    console.print(
        Panel(text, border_style="magenta", title="KNOWLEDGE_EVOLUTION", title_align="left")
    )
    console.print(f"   [dim]Context:[/dim] {issue[:70]}...", style="magenta")


def log_hop(hop_num: int, max_hops: int) -> None:
    """Log the current tool hop counter."""
    console.print(
        f"   [dim]↳ SEQUENCE_STEP {hop_num}/{max_hops}[/dim]",
        style="cyan"
    )


def log_error(message: str) -> None:
    """Log an error with red styling."""
    console.print(f"   [bold red]❌ ERROR:[/bold red] {message}", style="red")


def log_info(message: str) -> None:
    """Log general info."""
    console.print(f"   [bold blue]ℹ️ INFO:[/bold blue] {message}", style="blue")


def log_success(message: str) -> None:
    """Log success info."""
    console.print(f"   [bold green]✅ SUCCESS:[/bold green] {message}", style="green")


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


def print_response(content: str, source: str = "LIVE_DATA") -> None:
    """Pretty-print the assistant's final response with table extraction."""
    import re
    from rich.markdown import Markdown
    from rich.table import Table
    
    # 1. Identify tables (basic markdown table regex)
    table_pattern = r"((?:\|.*\|(?:\n|$))+)"
    tables = re.findall(table_pattern, content)
    
    # 2. Print main panel (without tables or with placeholders)
    clean_content = content
    if tables:
        for i, t in enumerate(tables):
            clean_content = clean_content.replace(t, f"\n[bold cyan]-- SEE TABLE {i+1} BELOW --[/bold cyan]\n")
            
    console.print(get_response_panel(clean_content, source))
    
    # 3. Print extracted tables using full width
    if tables:
        for t in tables:
            console.print("\n")
            console.print(Markdown(t))


def get_response_panel(content: str, source: str = "LIVE_DATA") -> Panel:
    """Return the assistant's response as a rich Panel."""
    from rich.markdown import Markdown
    color = "bright_green" if source == "LIVE_DATA" else "bright_yellow"
    return Panel(
        Markdown(content),
        border_style=color,
        title=f"[bold {color}]🤖 MISSION_ASSISTANT[/bold {color}]",
        title_align="left",
        padding=(1, 2),
        subtitle=f"[dim]Transmission Complete | SOURCE: {source}[/dim]",
        subtitle_align="right"
    )
