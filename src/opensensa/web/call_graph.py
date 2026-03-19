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

"""SSE-emitting call graph adapter for the web frontend.

Wraps the terminal ``CallGraph`` and pushes JSON-serializable events to an
``asyncio.Queue`` that the SSE endpoint drains.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional


# ---------------------------------------------------------------------------
# Lightweight node (mirrors interactive/call_graph._CallNode)
# ---------------------------------------------------------------------------

@dataclass
class CallNode:
    """A single node in the web call graph."""

    id: str
    label: str
    kind: str  # "tool", "delegation", "llm", "agent"
    status: str = "running"  # running | completed | failed
    start_time: float = field(default_factory=time.monotonic)
    end_time: Optional[float] = None
    duration_ms: Optional[int] = None
    result_preview: Optional[str] = None
    children: list["CallNode"] = field(default_factory=list)

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

    def to_dict(self) -> dict[str, Any]:
        """Serialize this node (and its children) to a plain dict."""
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "result_preview": self.result_preview,
            "children": [c.to_dict() for c in self.children],
        }


# ---------------------------------------------------------------------------
# WebCallGraph — pushes SSE events
# ---------------------------------------------------------------------------

class WebCallGraph:
    """Call graph that emits SSE events instead of rendering Rich trees.

    Each event method pushes a JSON message to an asyncio Queue.
    The SSE endpoint reads from this queue and streams to the browser.
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._root_nodes: list[CallNode] = []
        self._active_stack: list[CallNode] = []
        self._node_map: dict[str, CallNode] = {}
        self._key_seq: int = 0
        self._turn_start: float = time.monotonic()
        self._total_tokens: int = 0
        self._llm_calls: int = 0
        self._tool_calls: int = 0
        self._delegations: int = 0
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._finished = False

    # -- Key generation ------------------------------------------------------

    def _next_key(self, prefix: str) -> str:
        self._key_seq += 1
        return f"{prefix}:{self._key_seq}"

    def _find_running(self, prefix: str) -> CallNode | None:
        for key in reversed(list(self._node_map)):
            if key.startswith(prefix + ":"):
                node = self._node_map[key]
                if node.status == "running":
                    return node
        return None

    # -- SSE event helpers ---------------------------------------------------

    def _emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Push an SSE event onto the queue."""
        payload: dict[str, Any] = {"event": event_type}
        if data:
            payload.update(data)
        # Include the full tree snapshot so the client can re-render
        payload["tree"] = [n.to_dict() for n in self._root_nodes]
        payload["stats"] = {
            "tool_calls": self._tool_calls,
            "delegations": self._delegations,
            "llm_calls": self._llm_calls,
            "total_tokens": self._total_tokens,
            "elapsed_ms": int((time.monotonic() - self._turn_start) * 1000),
        }
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # drop event if queue is full (shouldn't happen)

    def _add_node(self, node: CallNode, key: str) -> None:
        self._node_map[key] = node
        if self._active_stack:
            self._active_stack[-1].children.append(node)
        else:
            self._root_nodes.append(node)

    # -- Event methods (same interface as interactive CallGraph) -------------

    def start_llm(self, agent_name: str | None = None) -> None:
        label = f"LLM → {agent_name}" if agent_name else "LLM call"
        key = self._next_key("llm")
        node = CallNode(id=key, label=label, kind="llm")
        self._add_node(node, key)
        self._llm_calls += 1
        self._emit("llm_start", {"node_id": key, "label": label})

    def end_llm(
        self,
        agent_name: str | None = None,
        duration_ms: int = 0,
        tokens: int = 0,
    ) -> None:
        node = self._find_running("llm")
        if node:
            result = f"{tokens} tokens" if tokens else None
            node.finish(duration_ms=duration_ms, result_preview=result)
            self._total_tokens += tokens
            if self._active_stack and self._active_stack[-1] is node:
                self._active_stack.pop()
            self._emit("llm_end", {
                "node_id": node.id,
                "duration_ms": duration_ms,
                "tokens": tokens,
            })

    def start_tool(self, tool_name: str) -> None:
        key = self._next_key("tool")
        if tool_name == "delegate":
            node = CallNode(id=key, label="delegating…", kind="delegation")
            self._add_node(node, key)
            self._delegations += 1
        else:
            node = CallNode(id=key, label=tool_name, kind="tool")
            self._add_node(node, key)
            self._tool_calls += 1
        self._emit("tool_start", {"node_id": key, "tool": tool_name})

    def end_tool(
        self,
        tool_name: str,
        duration_ms: int = 0,
        result: str | None = None,
    ) -> None:
        if tool_name == "delegate":
            node = self._find_running("tool")
            if node and node.kind != "delegation":
                node = None
        else:
            node = self._find_running("tool")
            if node and node.label != tool_name:
                node = None
        if not node:
            return

        if tool_name == "delegate" and result:
            self._finish_delegate_node(node, result, duration_ms)
        else:
            preview = result[:80].replace("\n", " ") if result else None
            node.finish(duration_ms=duration_ms, result_preview=preview)

        if self._active_stack and self._active_stack[-1] is node:
            self._active_stack.pop()

        self._emit("tool_end", {
            "node_id": node.id,
            "tool": tool_name,
            "duration_ms": duration_ms,
            "result_preview": node.result_preview,
        })

    def start_delegation(self, from_agent: str, to_agent: str, *, message: str = "") -> None:
        key = self._next_key("delegation")
        label = f"{from_agent} → {to_agent}"
        node = CallNode(id=key, label=label, kind="delegation")
        self._add_node(node, key)
        self._active_stack.append(node)
        self._delegations += 1
        self._emit("delegation_start", {
            "node_id": key,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "message": message,
        })

    def end_delegation(self, to_agent: str, duration_ms: int = 0, *, response: str = "") -> None:
        node = self._find_running("delegation")
        if node:
            node.finish(duration_ms=duration_ms)
            if self._active_stack and self._active_stack[-1] is node:
                self._active_stack.pop()
            self._emit("delegation_end", {
                "node_id": node.id,
                "to_agent": to_agent,
                "duration_ms": duration_ms,
                "response": response,
            })

    def start_agent(self, agent_name: str) -> None:
        if agent_name != self.agent_name:
            key = self._next_key("agent")
            node = CallNode(id=key, label=agent_name, kind="agent")
            self._add_node(node, key)
            self._emit("agent_start", {"node_id": key, "agent": agent_name})

    def end_agent(self, agent_name: str, duration_ms: int = 0) -> None:
        node = self._find_running("agent")
        if node:
            node.finish(duration_ms=duration_ms)
            if self._active_stack and self._active_stack[-1] is node:
                self._active_stack.pop()
            self._emit("agent_end", {
                "node_id": node.id,
                "agent": agent_name,
                "duration_ms": duration_ms,
            })

    def update_delegation_target(self, agent_name: str) -> None:
        node = self._find_running("tool")
        if node and node.kind == "delegation":
            node.label = f"delegate → {agent_name}"
            self._emit("delegation_update", {"node_id": node.id, "agent": agent_name})

    def add_delegation_sub_event(
        self,
        event_type: str,
        tool_name: str,
        *,
        agent_name: str | None = None,
        tools_used: list[dict] | None = None,
    ) -> None:
        node = self._find_running("tool")
        if not node or node.kind != "delegation":
            return

        if event_type == "tool_start":
            key = self._next_key("sub_tool")
            if tool_name == "delegate" and agent_name:
                label = f"delegate → {agent_name}"
            elif tool_name == "delegate":
                label = "delegating…"
            else:
                label = tool_name
            child = CallNode(
                id=key,
                label=label,
                kind=("delegation" if tool_name == "delegate" else "tool"),
            )
            node.children.append(child)
        elif event_type == "tool_end":
            for child in reversed(node.children):
                if child.status != "running":
                    continue
                if tool_name == "delegate" and child.kind == "delegation":
                    if agent_name:
                        child.label = f"delegate → {agent_name}"
                    child.finish()
                    break
                elif child.label == tool_name and child.kind == "tool":
                    child.finish()
                    break

        self._emit("delegation_sub_event", {
            "parent_id": node.id,
            "sub_event": event_type,
            "tool": tool_name,
        })

    # -- Delegate result parsing ---------------------------------------------

    def _finish_delegate_node(
        self, node: CallNode, result_json: str, duration_ms: int
    ) -> None:
        try:
            data = json.loads(result_json)
        except (ValueError, TypeError):
            node.finish(duration_ms=duration_ms, result_preview=result_json[:80])
            return

        agent_name = data.get("agent", "")
        status = data.get("status", "unknown")

        if agent_name:
            node.label = f"delegate → {agent_name}"
            node.kind = "delegation"

        tools_used = data.get("tools_used", [])
        if tools_used:
            node.children.clear()
            self._add_tool_children(node, tools_used)

        if status == "success":
            node.finish(duration_ms=duration_ms, result_preview="completed")
        elif status == "error":
            error_msg = data.get("error", "unknown error")[:60]
            node.finish(duration_ms=duration_ms, result_preview=error_msg, status="failed")
        else:
            node.finish(duration_ms=duration_ms)

    def _add_tool_children(self, parent: CallNode, tools_used: list[dict]) -> None:
        for tool_info in tools_used:
            tname = tool_info.get("name", "unknown")
            agent = tool_info.get("agent")
            nested = tool_info.get("tools_used", [])
            key = self._next_key("sub_tool")

            if tname == "delegate" and agent:
                child = CallNode(
                    id=key,
                    label=f"delegate → {agent}",
                    kind="delegation",
                    status="completed",
                )
                child.end_time = child.start_time
                self._add_tool_children(child, nested)
            else:
                child = CallNode(
                    id=key, label=tname, kind="tool", status="completed",
                )
                child.end_time = child.start_time

            parent.children.append(child)

    # -- Stats ---------------------------------------------------------------

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._turn_start) * 1000)

    @property
    def is_empty(self) -> bool:
        return len(self._root_nodes) == 0

    # -- SSE stream ----------------------------------------------------------

    def finish(self, response: str | None = None) -> None:
        """Signal that the agent turn is complete."""
        self._emit("turn_complete", {
            "response": response,
        })
        self._finished = True

    def error(self, message: str) -> None:
        """Signal that the agent turn failed."""
        self._emit("turn_error", {"error": message})
        self._finished = True

    async def events(self) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted strings. Blocks until events arrive or turn finishes."""
        while True:
            try:
                payload = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if payload.get("event") in ("turn_complete", "turn_error"):
                    return
            except asyncio.TimeoutError:
                # Send keepalive to prevent connection timeout
                yield ": keepalive\n\n"
                if self._finished:
                    return
