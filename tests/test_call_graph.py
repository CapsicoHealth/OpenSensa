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

"""Tests for the live call-graph renderable."""

from __future__ import annotations

import time

import pytest
from rich.console import Console

from opensensa.interactive.call_graph import CallGraph, _CallNode


# ---------------------------------------------------------------------------
# _CallNode basics
# ---------------------------------------------------------------------------

class TestCallNode:
    def test_defaults(self):
        node = _CallNode(label="test", kind="tool")
        assert node.status == "running"
        assert node.end_time is None
        assert node.duration_ms is None
        assert node.children == []

    def test_finish_sets_fields(self):
        node = _CallNode(label="test", kind="tool")
        node.finish(duration_ms=42, result_preview="ok", status="completed")
        assert node.status == "completed"
        assert node.duration_ms == 42
        assert node.result_preview == "ok"
        assert node.end_time is not None

    def test_finish_auto_duration(self):
        node = _CallNode(label="test", kind="tool")
        time.sleep(0.02)
        node.finish()
        assert node.duration_ms is not None
        assert node.duration_ms >= 15  # at least ~20ms


# ---------------------------------------------------------------------------
# CallGraph — event methods
# ---------------------------------------------------------------------------

class TestCallGraphEvents:
    def test_start_end_tool(self):
        g = CallGraph(agent_name="test-agent")
        assert g.is_empty

        g.start_tool("csv_formatter")
        assert not g.is_empty
        assert g._tool_calls == 1
        assert len(g._root_nodes) == 1
        assert g._root_nodes[0].status == "running"

        g.end_tool("csv_formatter", duration_ms=100, result="3 rows")
        assert g._root_nodes[0].status == "completed"
        assert g._root_nodes[0].duration_ms == 100
        assert g._tool_calls == 1

    def test_start_end_llm(self):
        g = CallGraph(agent_name="test-agent")
        g.start_llm("test-agent")
        assert g._llm_calls == 1

        g.end_llm("test-agent", duration_ms=500, tokens=120)
        assert g._total_tokens == 120
        assert g._root_nodes[0].status == "completed"

    def test_multiple_tools_sequential(self):
        g = CallGraph(agent_name="test-agent")
        g.start_tool("tool_a")
        g.end_tool("tool_a", duration_ms=50)
        g.start_tool("tool_b")
        g.end_tool("tool_b", duration_ms=60)

        assert len(g._root_nodes) == 2
        assert g._tool_calls == 2

    def test_delegation_nesting(self):
        """Children of a delegation should nest under it."""
        g = CallGraph(agent_name="agent-a")

        g.start_tool("tool_before")
        g.end_tool("tool_before", duration_ms=10)

        g.start_delegation("agent-a", "agent-b")
        g.start_tool("tool_inside")
        g.end_tool("tool_inside", duration_ms=20)
        g.end_delegation("agent-b", duration_ms=200)

        g.start_tool("tool_after")
        g.end_tool("tool_after", duration_ms=10)

        # Root: tool_before, delegation, tool_after
        assert len(g._root_nodes) == 3
        assert g._root_nodes[1].kind == "delegation"
        # tool_inside is nested under the delegation
        assert len(g._root_nodes[1].children) == 1
        assert g._root_nodes[1].children[0].label == "tool_inside"
        assert g._delegations == 1

    def test_nested_delegations(self):
        """A → B → C: tools inside C nest two levels deep."""
        g = CallGraph(agent_name="a")

        g.start_delegation("a", "b")
        g.start_delegation("b", "c")
        g.start_tool("deep_tool")
        g.end_tool("deep_tool", duration_ms=5)
        g.end_delegation("c", duration_ms=50)
        g.end_delegation("b", duration_ms=100)

        # Root: delegation a→b
        assert len(g._root_nodes) == 1
        del_b = g._root_nodes[0]
        assert del_b.kind == "delegation"
        # Under a→b: delegation b→c
        assert len(del_b.children) == 1
        del_c = del_b.children[0]
        assert del_c.kind == "delegation"
        # Under b→c: deep_tool
        assert len(del_c.children) == 1
        assert del_c.children[0].label == "deep_tool"

    def test_agent_start_skips_root_agent(self):
        """start_agent for the root agent should not create a node."""
        g = CallGraph(agent_name="main-agent")
        g.start_agent("main-agent")
        assert g.is_empty  # no node for the root agent

    def test_agent_start_shows_sub_agent(self):
        g = CallGraph(agent_name="main-agent")
        g.start_agent("sub-agent")
        assert not g.is_empty
        assert g._root_nodes[0].kind == "agent"

    def test_elapsed_ms(self):
        g = CallGraph(agent_name="test-agent")
        time.sleep(0.02)
        assert g.elapsed_ms >= 15


# ---------------------------------------------------------------------------
# CallGraph — delegate tool parsing
# ---------------------------------------------------------------------------

class TestCallGraphDelegateHandling:
    def test_delegate_shows_agent_name(self):
        """end_tool for delegate should parse JSON and show agent name."""
        import json

        g = CallGraph(agent_name="orchestrator")
        g.start_tool("delegate")

        # start_tool("delegate") should show as delegation, not tool
        assert g._root_nodes[0].kind == "delegation"
        assert g._delegations == 1
        assert g._tool_calls == 0  # delegate is counted as delegation

        result = json.dumps({
            "status": "success",
            "agent": "credit-score-agent",
            "result": {},
        })
        g.end_tool("delegate", duration_ms=5000, result=result)

        node = g._root_nodes[0]
        assert "credit-score-agent" in node.label
        assert node.kind == "delegation"
        assert node.status == "completed"

    def test_delegate_shows_sub_agent_tools(self):
        """When tools_used is present, they should appear as child nodes."""
        import json

        g = CallGraph(agent_name="orchestrator")
        g.start_tool("delegate")

        result = json.dumps({
            "status": "success",
            "agent": "data-analyst",
            "tools_used": [{"name": "csv_formatter"}, {"name": "run_query"}],
            "result": {},
        })
        g.end_tool("delegate", duration_ms=8000, result=result)

        node = g._root_nodes[0]
        assert "data-analyst" in node.label
        assert len(node.children) == 2
        assert node.children[0].label == "csv_formatter"
        assert node.children[0].kind == "tool"
        assert node.children[0].status == "completed"
        assert node.children[1].label == "run_query"

    def test_delegate_error_shows_failed(self):
        """A failed delegation should show error status."""
        import json

        g = CallGraph(agent_name="orchestrator")
        g.start_tool("delegate")

        result = json.dumps({
            "status": "error",
            "error": "Agent not found",
        })
        g.end_tool("delegate", duration_ms=100, result=result)

        node = g._root_nodes[0]
        assert node.status == "failed"

    def test_delegate_invalid_json_falls_back(self):
        """Non-JSON result should fall back to truncated preview."""
        g = CallGraph(agent_name="orchestrator")
        g.start_tool("delegate")
        g.end_tool("delegate", duration_ms=100, result="not json")

        node = g._root_nodes[0]
        assert node.status == "completed"
        assert node.result_preview == "not json"

    def test_delegate_renders_nested_tree(self):
        """Delegate with tool children should render as a nested tree."""
        import json

        g = CallGraph(agent_name="main")
        g.start_tool("delegate")
        result = json.dumps({
            "status": "success",
            "agent": "helper",
            "tools_used": [{"name": "search"}],
            "result": {},
        })
        g.end_tool("delegate", duration_ms=3000, result=result)

        c = Console(width=80, force_terminal=True)
        with c.capture() as capture:
            c.print(g)
        output = capture.get()
        assert "helper" in output
        assert "search" in output

    def test_nested_delegation_chain(self):
        """A → delegate(B) → delegate(C) should render recursively."""
        import json

        g = CallGraph(agent_name="loan-agent")
        g.start_tool("delegate")

        # B delegated to C, and C used lookup_history
        result = json.dumps({
            "status": "success",
            "agent": "credit-score-agent",
            "tools_used": [
                {
                    "name": "delegate",
                    "agent": "credit-history-agent",
                    "tools_used": [{"name": "lookup_history"}],
                },
            ],
            "result": {},
        })
        g.end_tool("delegate", duration_ms=15000, result=result)

        node = g._root_nodes[0]
        assert "credit-score-agent" in node.label
        # First child: nested delegation to credit-history-agent
        assert len(node.children) == 1
        nested = node.children[0]
        assert nested.kind == "delegation"
        assert "credit-history-agent" in nested.label
        # Inside that: lookup_history tool
        assert len(nested.children) == 1
        assert nested.children[0].label == "lookup_history"
        assert nested.children[0].kind == "tool"

        # Verify rendering includes all levels
        c = Console(width=80, force_terminal=True)
        with c.capture() as capture:
            c.print(g)
        output = capture.get()
        assert "credit-score-agent" in output
        assert "credit-history-agent" in output
        assert "lookup_history" in output

    def test_delegate_start_shows_delegating(self):
        """start_tool('delegate') should show 'delegating…' not 'delegate'."""
        g = CallGraph(agent_name="main")
        g.start_tool("delegate")

        c = Console(width=80, force_terminal=True)
        with c.capture() as capture:
            c.print(g)
        output = capture.get()
        assert "delegating" in output

    def test_update_delegation_target(self):
        """update_delegation_target should change label of in-progress delegation."""
        g = CallGraph(agent_name="main")
        g.start_tool("delegate")

        # Initially shows "delegating…"
        node = g._root_nodes[0]
        assert "delegating" in node.label

        # After target is known, show the agent name
        g.update_delegation_target("credit-score-agent")
        assert "credit-score-agent" in node.label
        assert node.kind == "delegation"

    def test_update_delegation_target_ignored_when_completed(self):
        """update_delegation_target should not change a completed node."""
        import json

        g = CallGraph(agent_name="main")
        g.start_tool("delegate")
        g.end_tool("delegate", duration_ms=100, result=json.dumps({
            "status": "success", "agent": "agent-a", "result": {},
        }))
        # Now try to update — should be ignored (node is completed)
        g.update_delegation_target("agent-b")
        assert "agent-a" in g._root_nodes[0].label

    def test_add_delegation_sub_event_tool_start(self):
        """Real-time tool_start should add a running child to the delegation."""
        g = CallGraph(agent_name="main")
        g.start_tool("delegate")
        g.update_delegation_target("sub-agent")

        g.add_delegation_sub_event("tool_start", "csv_formatter")
        node = g._root_nodes[0]
        assert len(node.children) == 1
        assert node.children[0].label == "csv_formatter"
        assert node.children[0].kind == "tool"
        assert node.children[0].status == "running"

    def test_add_delegation_sub_event_tool_end(self):
        """Real-time tool_end should mark the matching child completed."""
        g = CallGraph(agent_name="main")
        g.start_tool("delegate")

        g.add_delegation_sub_event("tool_start", "search")
        g.add_delegation_sub_event("tool_end", "search")

        child = g._root_nodes[0].children[0]
        assert child.status == "completed"

    def test_nested_delegation_via_start_delegation(self):
        """Nested delegation B→C should nest under the merged A→B node."""
        g = CallGraph(agent_name="main")
        # A's delegate tool starts
        g.start_tool("delegate")
        # Phase 14: delegation event merges with the tool node
        g.start_delegation("main", "agent-b")

        # Only one root node (merged)
        assert len(g._root_nodes) == 1
        assert "main → agent-b" in g._root_nodes[0].label

        # Nested delegation B→C (should NOT merge — creates a child)
        g.start_delegation("agent-b", "agent-c")
        assert len(g._root_nodes) == 1  # still one root
        assert len(g._root_nodes[0].children) == 1
        child = g._root_nodes[0].children[0]
        assert child.kind == "delegation"
        assert "agent-b → agent-c" in child.label

        # End nested delegation
        g.end_delegation("agent-c", duration_ms=50)
        assert child.status == "completed"

        # End parent delegation
        g.end_delegation("agent-b")

    def test_realtime_children_preserved_over_final_tools_used(self):
        """Real-time children from event forwarding are kept when they exist.

        The ``tools_used`` from the final result is only used as a fallback
        when no real-time children were collected during the delegation.
        """
        import json

        g = CallGraph(agent_name="main")
        g.start_tool("delegate")

        # Real-time events add children
        g.add_delegation_sub_event("tool_start", "tool_a")
        g.add_delegation_sub_event("tool_end", "tool_a")
        assert len(g._root_nodes[0].children) == 1

        # Final result has tools_used, but real-time children are preserved
        result = json.dumps({
            "status": "success",
            "agent": "sub-agent",
            "tools_used": [{"name": "tool_a"}, {"name": "tool_b"}],
            "result": {},
        })
        g.end_tool("delegate", duration_ms=5000, result=result)

        node = g._root_nodes[0]
        # Real-time child kept (tool_b from tools_used is NOT added)
        assert len(node.children) == 1
        assert node.children[0].label == "tool_a"

    def test_final_tools_used_fallback_when_no_realtime_children(self):
        """tools_used from end_tool result populates children as a fallback."""
        import json

        g = CallGraph(agent_name="main")
        g.start_tool("delegate")

        # No real-time events — children list is empty
        assert len(g._root_nodes[0].children) == 0

        result = json.dumps({
            "status": "success",
            "agent": "sub-agent",
            "tools_used": [{"name": "tool_a"}, {"name": "tool_b"}],
            "result": {},
        })
        g.end_tool("delegate", duration_ms=5000, result=result)

        node = g._root_nodes[0]
        assert len(node.children) == 2
        assert node.children[0].label == "tool_a"
        assert node.children[1].label == "tool_b"

    def test_spinner_animates(self):
        """Successive renders should cycle through different spinner frames."""
        from opensensa.interactive.call_graph import SPINNER_FRAMES

        g = CallGraph(agent_name="main")
        g.start_tool("running_tool")

        c = Console(width=80, force_terminal=True)
        outputs = []
        for _ in range(3):
            with c.capture() as capture:
                c.print(g)
            outputs.append(capture.get())

        # At least two distinct spinner characters should appear
        chars_found = set()
        for o in outputs:
            for ch in SPINNER_FRAMES:
                if ch in o:
                    chars_found.add(ch)
        assert len(chars_found) >= 2, f"Spinner didn't animate: found {chars_found}"


# ---------------------------------------------------------------------------
# CallGraph — rendering
# ---------------------------------------------------------------------------

class TestCallGraphRendering:
    def test_renders_without_crash(self):
        """Smoke test: rendering to a string should not raise."""
        g = CallGraph(agent_name="test-agent")
        g.start_tool("csv_formatter")
        g.end_tool("csv_formatter", duration_ms=42, result="ok")

        c = Console(width=80, force_terminal=True)
        with c.capture() as capture:
            c.print(g)
        output = capture.get()
        assert "csv_formatter" in output

    def test_renders_empty_graph(self):
        """An empty graph should show 'Thinking…'."""
        g = CallGraph(agent_name="test-agent")
        c = Console(width=80, force_terminal=True)
        with c.capture() as capture:
            c.print(g)
        output = capture.get()
        assert "Thinking" in output

    def test_make_summary_panel(self):
        """make_summary should return a Panel with stats."""
        g = CallGraph(agent_name="test-agent")
        g.start_tool("tool_a")
        g.end_tool("tool_a", duration_ms=50)
        g.start_tool("tool_b")
        g.end_tool("tool_b", duration_ms=60)

        panel = g.make_summary()
        c = Console(width=80, force_terminal=True)
        with c.capture() as capture:
            c.print(panel)
        output = capture.get()
        assert "tool_a" in output
        assert "tool_b" in output
        assert "2 tool(s)" in output

    def test_delegation_renders_nested(self):
        """Delegation children should be indented in the rendered tree."""
        g = CallGraph(agent_name="a")
        g.start_delegation("a", "b")
        g.start_tool("nested_tool")
        g.end_tool("nested_tool", duration_ms=10)
        g.end_delegation("b", duration_ms=100)

        c = Console(width=80, force_terminal=True)
        with c.capture() as capture:
            c.print(g)
        output = capture.get()
        assert "a → b" in output
        assert "nested_tool" in output
