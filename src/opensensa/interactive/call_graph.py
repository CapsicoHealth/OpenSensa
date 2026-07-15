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

"""Live call-graph renderable for the OpenSensa chat TUI.

Displays a real-time Rich ``Tree`` showing tool calls, LLM invocations, and
agent delegations as they happen during an agent turn.  Designed to be used
inside a ``rich.live.Live`` context that auto-refreshes the terminal.

Usage::

    graph = CallGraph(agent_name="clinical-researcher")
    with Live(graph, console=console, refresh_per_second=8):
        # hooks push events into the graph
        graph.start_tool("csv_formatter")
        graph.end_tool("csv_formatter", duration_ms=320, result="3 rows")
        ...
    # after Live exits, print the final tree with graph.make_summary()
"""

from __future__ import annotations

import json as _json
import time
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console, ConsoleOptions, RenderResult
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree


# ---------------------------------------------------------------------------
# Data model — one node per tool/delegation/LLM call
# ---------------------------------------------------------------------------

@dataclass
class _CallNode:
    """A single node in the call graph."""

    label: str
    kind: str  # "tool", "delegation", "llm", "agent"
    start_time: float = field(default_factory=time.monotonic)
    end_time: Optional[float] = None
    duration_ms: Optional[int] = None
    result_preview: Optional[str] = None
    children: list["_CallNode"] = field(default_factory=list)
    status: str = "running"  # running | completed | failed

    def finish(
        self,
        *,
        duration_ms: int | None = None,
        result_preview: str | None = None,
        status: str = "completed",
    ) -> None:
        self.end_time = time.monotonic()
        self.duration_ms = duration_ms or int((self.end_time - self.start_time) * 1000)
        self.result_preview = result_preview
        self.status = status


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------

_KIND_ICONS = {
    "tool": "🔧",
    "delegation": "🤖",
    "llm": "💬",
    "agent": "🏷️ ",
}

_STATUS_STYLE = {
    "running": "yellow",
    "completed": "green",
    "failed": "red",
}

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _render_node(node: _CallNode, frame: int = 0) -> Text:
    """Build a Rich ``Text`` for a single call node."""
    icon = _KIND_ICONS.get(node.kind, "●")
    style = _STATUS_STYLE.get(node.status, "dim")

    parts = Text()
    parts.append(f"{icon} ", style=style)
    parts.append(node.label, style=f"bold {style}")

    if node.status == "running":
        spinner = SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]
        parts.append(f"  {spinner}", style="yellow")
    elif node.duration_ms is not None:
        parts.append(f"  ({node.duration_ms}ms)", style="dim")

    if node.status == "completed" and node.result_preview:
        preview = node.result_preview[:80].replace("\n", " ")
        parts.append(f"  → {preview}", style="dim")

    if node.status == "completed":
        parts.append("  ✓", style="green")
    elif node.status == "failed":
        parts.append("  ✗", style="red")

    return parts


# ---------------------------------------------------------------------------
# CallGraph — the main renderable
# ---------------------------------------------------------------------------

class CallGraph:
    """A live-updating call tree that tracks agent activity during a turn.

    This class is both a data collector (hooks push events into it) and a
    Rich renderable (``Live`` calls ``__rich_console__`` to paint it).
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._root_nodes: list[_CallNode] = []
        self._active_stack: list[_CallNode] = []
        self._turn_start: float = time.monotonic()
        self._total_tokens: int = 0
        self._llm_calls: int = 0
        self._tool_calls: int = 0
        self._delegations: int = 0
        # Key → node lookup.  Keys use a sequence counter to stay unique
        # even when the same tool is called multiple times in one turn.
        self._node_map: dict[str, _CallNode] = {}
        self._key_seq: int = 0
        self._frame: int = 0

    # -- Event methods (called from hooks) ----------------------------------

    def _next_key(self, prefix: str) -> str:
        """Return a unique map key like ``tool:delegate:3``."""
        self._key_seq += 1
        return f"{prefix}:{self._key_seq}"

    def _find_running(self, prefix: str) -> _CallNode | None:
        """Find the most recent *running* node whose key starts with *prefix*."""
        # Iterate in reverse insertion order (Python 3.7+ dict guarantee)
        for key in reversed(list(self._node_map)):
            if key.startswith(prefix + ":"):
                node = self._node_map[key]
                if node.status == "running":
                    return node
        return None

    # -- Event methods (called from hooks) ----------------------------------

    def start_llm(self, agent_name: str | None = None) -> None:
        """Record the start of an LLM call."""
        label = f"LLM → {agent_name}" if agent_name else "LLM call"
        node = _CallNode(label=label, kind="llm")
        self._add_node(node, key=self._next_key("llm"))
        self._llm_calls += 1

    def end_llm(
        self,
        agent_name: str | None = None,
        duration_ms: int = 0,
        tokens: int = 0,
    ) -> None:
        """Record the end of an LLM call."""
        node = self._find_running("llm")
        if node:
            result = f"{tokens} tokens" if tokens else None
            node.finish(duration_ms=duration_ms, result_preview=result)
            self._total_tokens += tokens
            # Pop from active stack if it's the top
            if self._active_stack and self._active_stack[-1] is node:
                self._active_stack.pop()

    def start_tool(self, tool_name: str) -> None:
        """Record the start of a tool call."""
        if tool_name == "delegate":
            # Show as a delegation in progress so it doesn't look like a glitch
            node = _CallNode(label="delegating\u2026", kind="delegation")
            self._add_node(node, key=self._next_key("tool"))
            self._delegations += 1
        else:
            node = _CallNode(label=tool_name, kind="tool")
            self._add_node(node, key=self._next_key("tool"))
            self._tool_calls += 1

    def end_tool(
        self,
        tool_name: str,
        duration_ms: int = 0,
        result: str | None = None,
    ) -> None:
        """Record the end of a tool call."""
        # Find the most recent running tool node.  For the delegate tool
        # we match by kind since its label changes during execution.
        if tool_name == "delegate":
            node = self._find_running("tool")
            # Verify it's actually a delegation node
            if node and node.kind != "delegation":
                node = None
        else:
            node = self._find_running("tool")
            # Verify the label matches the tool name
            if node and node.label != tool_name:
                node = None
        if not node:
            return

        # Special handling for the delegate tool — parse JSON result to
        # show the target agent name and any sub-agent tool calls.
        if tool_name == "delegate" and result:
            self._finish_delegate_node(node, result, duration_ms)
        else:
            preview = result[:80].replace("\n", " ") if result else None
            node.finish(duration_ms=duration_ms, result_preview=preview)

        # Pop from active stack if it's the top
        if self._active_stack and self._active_stack[-1] is node:
            self._active_stack.pop()

    def start_delegation(self, from_agent: str, to_agent: str, **kwargs) -> None:
        """Record the start of an agent-to-agent delegation.

        If ``start_tool("delegate")`` already created a placeholder node we
        *merge* into it (update the label, push it onto the active stack) so
        the tree only shows one entry per delegation.
        """
        # Try to merge with the placeholder created by start_tool("delegate").
        # Only merge if it hasn't been merged yet — a nested delegation
        # (B→C inside A→B) must NOT overwrite the parent node.
        existing = self._find_running("tool")
        if existing and existing.kind == "delegation" and not getattr(existing, '_merged', False):
            existing.label = f"{from_agent} → {to_agent}"
            existing._merged = True  # type: ignore[attr-defined]
            # Push as new context — subsequent calls nest under this delegation
            self._active_stack.append(existing)
            # Don't increment _delegations — already counted by start_tool
            return

        # Standalone delegation (no prior start_tool("delegate") call)
        label = f"{from_agent} → {to_agent}"
        node = _CallNode(label=label, kind="delegation")
        self._add_node(node, key=self._next_key("delegation"))
        self._active_stack.append(node)
        self._delegations += 1

    def end_delegation(self, to_agent: str, duration_ms: int = 0, **kwargs) -> None:
        """Record the end of an agent-to-agent delegation."""
        # Pop the delegation from the active stack
        if self._active_stack and self._active_stack[-1].kind == "delegation":
            node = self._active_stack.pop()
            # If merged with a tool node, don't finish here —
            # end_tool("delegate") will handle finishing with result parsing.
            if not getattr(node, '_merged', False):
                node.finish(duration_ms=duration_ms)
            return

        # Fallback: find by key prefix (standalone delegation node)
        node = self._find_running("delegation")
        if node:
            node.finish(duration_ms=duration_ms)

    def start_agent(self, agent_name: str) -> None:
        """Record an agent lifecycle start (for sub-agents during delegation)."""
        # Only show agent nodes when it's different from the root agent
        if agent_name != self.agent_name:
            node = _CallNode(label=agent_name, kind="agent")
            self._add_node(node, key=self._next_key("agent"))

    def end_agent(self, agent_name: str, duration_ms: int = 0) -> None:
        """Record an agent lifecycle end."""
        node = self._find_running("agent")
        if node:
            node.finish(duration_ms=duration_ms)
            if self._active_stack and self._active_stack[-1] is node:
                self._active_stack.pop()

    def update_delegation_target(self, agent_name: str) -> None:
        """Update the in-progress delegation node with the target agent name.

        Called by the delegate tool as soon as it knows which agent is
        being delegated to — before waiting for the response.  Skipped
        when ``start_delegation`` already set a proper label.
        """
        node = self._find_running("tool")
        if node and node.kind == "delegation" and not getattr(node, '_merged', False):
            node.label = f"delegate \u2192 {agent_name}"

    def add_delegation_sub_event(
        self,
        event_type: str,
        tool_name: str,
        *,
        agent_name: str | None = None,
        tools_used: list[dict] | None = None,
    ) -> None:
        """Push a real-time sub-agent tool event into the active delegation.

        The delegate tool calls this when it receives SSE events from the
        sub-agent's streaming execution, so the user can see what the
        sub-agent is doing *as it happens*.
        """
        # Find the active delegation node (the running tool:* with kind=delegation)
        node = self._find_running("tool")
        if not node or node.kind != "delegation":
            return

        # Skip delegate tool events — nested delegations are now handled
        # by start_delegation/end_delegation via Phase 14 event forwarding.
        if tool_name == "delegate":
            return

        if event_type == "tool_start":
            child = _CallNode(label=tool_name, kind="tool")
            node.children.append(child)

        elif event_type == "tool_end":
            # Find the latest running child that matches this tool
            for child in reversed(node.children):
                if child.status != "running":
                    continue
                if child.label == tool_name and child.kind == "tool":
                    child.finish()
                    break

    # -- Internal helpers ---------------------------------------------------

    def _add_node(self, node: _CallNode, key: str) -> None:
        """Add a node either as a child of the active context or at the root."""
        self._node_map[key] = node
        if self._active_stack:
            self._active_stack[-1].children.append(node)
        else:
            self._root_nodes.append(node)

    def _finish_delegate_node(
        self, node: _CallNode, result_json: str, duration_ms: int
    ) -> None:
        """Parse a delegate tool result and update the node nicely.

        Instead of showing raw JSON, this extracts the target agent name
        and any tool calls the sub-agent made, rendering them as children.
        """
        try:
            data = _json.loads(result_json)
        except (ValueError, TypeError):
            node.finish(duration_ms=duration_ms, result_preview=result_json[:80])
            return

        agent_name = data.get("agent", "")
        status = data.get("status", "unknown")

        # Update label to show target agent (skip if start_delegation
        # already set the proper "A → B" label via merge).
        if agent_name and not getattr(node, '_merged', False):
            node.label = f"delegate → {agent_name}"
            node.kind = "delegation"

        # Add child nodes for each tool the sub-agent called.
        # If the node already has real-time children (from event forwarding
        # during a merged delegation), keep them — they have richer detail.
        tools_used = data.get("tools_used", [])
        if tools_used and not node.children:
            self._add_tool_children(node, tools_used)

        # Set a clean result preview
        if status == "success":
            preview = "completed"
            node.finish(duration_ms=duration_ms, result_preview=preview)
        elif status == "error":
            error_msg = data.get("error", "unknown error")[:60]
            node.finish(
                duration_ms=duration_ms,
                result_preview=error_msg,
                status="failed",
            )
        else:
            node.finish(duration_ms=duration_ms)

    def _add_tool_children(
        self, parent: _CallNode, tools_used: list[dict]
    ) -> None:
        """Recursively add child nodes from a ``tools_used`` list.

        Each entry may be a plain ``{"name": "..."}`` or a nested
        delegation with ``{"name": "delegate", "agent": "...",
        "tools_used": [...]}``.
        """
        for tool_info in tools_used:
            tname = tool_info.get("name", "unknown")
            agent = tool_info.get("agent")
            nested = tool_info.get("tools_used", [])

            if tname == "delegate" and agent:
                # Nested delegation — show with delegation icon + agent name
                child = _CallNode(
                    label=f"delegate \u2192 {agent}",
                    kind="delegation",
                    status="completed",
                )
                child.end_time = child.start_time
                # Recurse into what that agent called
                self._add_tool_children(child, nested)
            else:
                child = _CallNode(
                    label=tname,
                    kind="tool",
                    status="completed",
                )
                child.end_time = child.start_time

            parent.children.append(child)

    # -- Stats --------------------------------------------------------------

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._turn_start) * 1000)

    @property
    def is_empty(self) -> bool:
        return len(self._root_nodes) == 0

    # -- Rich renderable ----------------------------------------------------

    def _build_tree(self) -> Tree:
        """Build a Rich ``Tree`` from the current call graph state."""
        # Header with agent name and elapsed time
        header = Text()
        header.append(f"  {self.agent_name}", style="bold cyan")

        tree = Tree(header)

        frame = self._frame

        def _add_children(parent_tree: Tree, nodes: list[_CallNode]) -> None:
            for node in nodes:
                label = _render_node(node, frame)
                branch = parent_tree.add(label)
                if node.children:
                    _add_children(branch, node.children)

        _add_children(tree, self._root_nodes)

        # If nothing has happened yet, show a waiting indicator
        if not self._root_nodes:
            tree.add(Text("  Thinking…", style="dim italic"))

        return tree

    def _build_footer(self) -> Text:
        """Status bar with counters."""
        footer = Text()
        if self._tool_calls:
            footer.append(f"  🔧 {self._tool_calls}", style="yellow")
        if self._delegations:
            if footer:
                footer.append("  │  ", style="dim")
            footer.append(f"  🤖 {self._delegations}", style="cyan")
        if self._total_tokens:
            if footer:
                footer.append("  │  ", style="dim")
            footer.append(f"  ⚡ {self._total_tokens} tok", style="dim")
        return footer

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        """Render the call graph as a bordered panel with a tree inside."""
        self._frame += 1
        tree = self._build_tree()
        footer = self._build_footer()

        # Combine tree + footer into the panel
        width = min(console.width, 72)

        yield Panel(
            tree,
            subtitle=str(footer) if footer.plain.strip() else None,
            subtitle_align="left",
            border_style="yellow",
            padding=(0, 1),
            width=width,
        )

    # -- Post-turn summary (printed after Live exits) -----------------------

    def make_summary(self) -> Panel:
        """Return a static Rich panel summarizing the completed turn.

        Call this after the agent turn finishes (outside of ``Live``) to
        print a final snapshot of what happened.
        """
        tree = self._build_tree()

        # Build a richer footer for the summary
        elapsed_s = self.elapsed_ms / 1000
        summary_parts = []
        if self._tool_calls:
            summary_parts.append(f"🔧 {self._tool_calls} tool(s)")
        if self._delegations:
            summary_parts.append(f"🤖 {self._delegations} delegation(s)")
        if self._total_tokens:
            summary_parts.append(f"⚡ {self._total_tokens} tokens")
        summary_parts.append(f"⏱  {elapsed_s:.1f}s")

        subtitle = "  ".join(summary_parts)

        return Panel(
            tree,
            subtitle=f"[dim]{subtitle}[/dim]",
            subtitle_align="left",
            border_style="dim yellow",
            padding=(0, 1),
            width=72,
        )
