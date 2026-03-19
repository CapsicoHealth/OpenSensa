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

"""Tests for the agent registry."""

import tempfile
from pathlib import Path

from opensensa.orchestrator.agent_registry import AgentDefinition, AgentRegistry


def test_parse_agent_definition():
    """Parse a frontmatter .md file into an AgentDefinition."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_file = Path(tmpdir) / "test-agent.md"
        agent_file.write_text("""---
name: test-agent
description: A test agent
model: gpt-4
tools:
  - add_numbers
  - list_tools
skills:
  - id: testing
    name: Testing
    description: Runs tests
    tags: [test]
input_modes: ["text/plain"]
output_modes: ["text/plain", "application/json"]
context_headers:
  X-Tenant-Id: acme
---

# Test Agent

You are a test agent. Do testing things.

## Guidelines
- Be thorough
""")
        defn = AgentDefinition.from_file(agent_file)
        assert defn.name == "test-agent"
        assert defn.description == "A test agent"
        assert defn.model == "gpt-4"
        assert defn.tools == ["add_numbers", "list_tools"]
        assert len(defn.skills) == 1
        assert defn.skills[0].id == "testing"
        assert defn.skills[0].tags == ["test"]
        assert defn.input_modes == ["text/plain"]
        assert defn.output_modes == ["text/plain", "application/json"]
        assert defn.context_headers == {"X-Tenant-Id": "acme"}
        assert "You are a test agent" in defn.system_prompt
        assert "---" not in defn.system_prompt  # Frontmatter should not leak


def test_agent_registry_scan():
    """AgentRegistry should discover .md files and track changes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = Path(tmpdir)

        # Create two agent files
        (agents_dir / "agent-a.md").write_text("""---
name: agent-a
description: Agent A
---

System prompt A
""")
        (agents_dir / "agent-b.md").write_text("""---
name: agent-b
description: Agent B
---

System prompt B
""")

        registry = AgentRegistry(agents_dir)
        agents = registry.scan()

        assert "agent-a" in agents
        assert "agent-b" in agents
        assert len(agents) == 2

        # Names list
        assert set(registry.agent_names()) == {"agent-a", "agent-b"}

        # Lookup by name
        a = registry.get("agent-a")
        assert a is not None
        assert a.description == "Agent A"


def test_agent_registry_ignores_non_md():
    """Non-.md files should be ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = Path(tmpdir)
        (agents_dir / "notes.txt").write_text("not an agent")
        (agents_dir / "script.py").write_text("print('hi')")
        (agents_dir / "real-agent.md").write_text("""---
name: real-agent
description: Real
---

Prompt
""")

        registry = AgentRegistry(agents_dir)
        assert registry.agent_names() == ["real-agent"]
