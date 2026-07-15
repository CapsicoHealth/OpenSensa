# ===========================================================================
# Copyright (C) 2025 CapsicoHealth Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===========================================================================

"""Rich terminal UI components for OpenSensa interactive chat.

Handles all visual rendering: welcome banner, agent responses (markdown),
tool call indicators, spinners, slash-command help, error display, etc.
"""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ---------------------------------------------------------------------------
# Themed console — single instance used everywhere
# ---------------------------------------------------------------------------

APP_THEME = Theme(
    {
        "agent.name": "bold cyan",
        "tool.name": "bold yellow",
        "user.prompt": "bold green",
        "info": "dim",
        "error": "bold red",
        "success": "bold green",
        "accent": "cyan",
        "dim": "dim",
    }
)

console = Console(theme=APP_THEME, highlight=False)


# ---------------------------------------------------------------------------
# Welcome / banner
# ---------------------------------------------------------------------------


def print_welcome(
    agent_name: str,
    description: str,
    model: str,
    tools: list[str],
) -> None:
    """Print the welcome banner with agent info."""
    tools_str = ", ".join(tools[:5])
    if len(tools) > 5:
        tools_str += f" (+{len(tools) - 5} more)"

    body = Text()
    body.append("opensensa", style="bold cyan")
    body.append("\n\n")
    body.append("  Agent  ", style="dim")
    body.append(agent_name, style="bold")
    body.append("\n")
    body.append("  Model  ", style="dim")
    body.append(model, style="bold")
    body.append("\n")
    body.append("  Tools  ", style="dim")
    body.append(tools_str or "none", style="bold yellow" if tools_str else "dim")
    body.append("\n\n")
    body.append(f"  {description}", style="dim italic")

    console.print()
    console.print(
        Panel(
            body,
            border_style="cyan",
            padding=(1, 3),
            width=min(console.width, 72),
        )
    )
    console.print()
    console.print(
        "  [dim]Type a message to chat. Use [bold]/help[/bold] for commands, "
        "[bold]/quit[/bold] to exit.[/dim]"
    )
    console.print()


# ---------------------------------------------------------------------------
# Agent responses
# ---------------------------------------------------------------------------


def print_agent_response(text: str, agent_name: str = "Agent") -> None:
    """Render the agent's response as rich Markdown inside a panel."""
    console.print()
    md = Markdown(text)
    console.print(
        Panel(
            md,
            title=f"[bold cyan]{agent_name}[/bold cyan]",
            title_align="left",
            border_style="cyan",
            padding=(1, 2),
            width=min(console.width, 80),
        )
    )
    console.print()


# ---------------------------------------------------------------------------
# Tool call indicators
# ---------------------------------------------------------------------------


def print_tool_call(tool_name: str) -> None:
    """Show that a tool is being invoked (shown in real-time via hooks)."""
    console.print(f"  [yellow]●[/yellow] [bold yellow]{tool_name}[/bold yellow]")


def print_tool_result(tool_name: str, result: str, max_len: int = 160) -> None:
    """Show a truncated tool result below the call indicator."""
    truncated = result[:max_len].replace("\n", " ").strip()
    if len(result) > max_len:
        truncated += "…"
    console.print(f"    [dim]└─ {truncated}[/dim]")


# ---------------------------------------------------------------------------
# Spinner / status
# ---------------------------------------------------------------------------


def get_spinner(message: str = "Thinking"):
    """Return a ``console.status()`` context manager that shows a spinner."""
    return console.status(f"  [dim]{message}…[/dim]", spinner="dots")


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


def print_error(message: str) -> None:
    console.print(f"\n  [bold red]✖ Error:[/bold red] {message}\n")


def print_info(message: str) -> None:
    console.print(f"\n  [dim]{message}[/dim]\n")


# ---------------------------------------------------------------------------
# Slash-command help
# ---------------------------------------------------------------------------


def print_help() -> None:
    tbl = Table(show_header=False, box=None, padding=(0, 2))
    tbl.add_column(style="bold cyan", min_width=18)
    tbl.add_column(style="dim")
    tbl.add_row("/help", "Show this help")
    tbl.add_row("/quit  or  Ctrl-D", "Exit chat")
    tbl.add_row("/clear", "Clear screen")
    tbl.add_row("/agents", "List available agents")
    tbl.add_row("/agent <name>", "Switch to a different agent")
    tbl.add_row("/tools", "List current agent's tools")
    tbl.add_row("/model", "Show current model")
    tbl.add_row("/reset", "Clear conversation history")
    tbl.add_row("/history", "Show conversation length")
    console.print()
    console.print(
        Panel(tbl, title="[bold]Commands[/bold]", title_align="left", border_style="dim", padding=(1, 1))
    )
    console.print()


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------


def print_agents_list(agents) -> None:
    """Pretty-print a list of AgentDefinition objects."""
    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    tbl.add_column("Agent", style="bold cyan")
    tbl.add_column("Model", style="dim")
    tbl.add_column("Description", style="dim")
    for a in agents:
        tbl.add_row(a.name, a.model, a.description[:55])
    console.print()
    console.print(tbl)
    console.print()


def print_tools_list(tools: list[str]) -> None:
    console.print()
    if not tools:
        console.print("  [dim]No tools configured for this agent.[/dim]")
    else:
        for t in sorted(tools):
            console.print(f"  [yellow]●[/yellow] {t}")
    console.print()


# ---------------------------------------------------------------------------
# Agent selector (when multiple agents exist)
# ---------------------------------------------------------------------------


def print_agent_selector(agents) -> None:
    """Print a numbered list of agents for the user to pick from."""
    console.print()
    console.print("  [bold]Select an agent:[/bold]")
    console.print()
    for i, a in enumerate(agents, 1):
        console.print(
            f"  [bold cyan]{i}[/bold cyan]  {a.name}  [dim]— {a.description[:50]}[/dim]"
        )
    console.print()
