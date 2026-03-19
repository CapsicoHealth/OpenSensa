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

"""Tests for framework-provided MCP tools.

Tests: create_agent, edit_agent, delete_agent, delegate, discover_agents, send_to_agent, list_tools.
"""

import re
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opensensa.config import AppConfig, ModelsConfig, ModelConfig, ServerConfig, AgentsConfig, ToolsConfig, LoggingConfig
from opensensa.orchestrator.agent_registry import AgentRegistry


# ---------------------------------------------------------------------------
# Helpers — lightweight MCP stub for registering tools
# ---------------------------------------------------------------------------

class FakeMCP:
    """Minimal stub that captures tool registrations."""

    def __init__(self):
        self._tools: dict[str, callable] = {}

    def tool(self, *args, **kwargs):
        def decorator(func):
            self._tools[func.__name__] = func
            return func
        return decorator

    def get_tool(self, name: str):
        return self._tools[name]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_mcp():
    return FakeMCP()


@pytest.fixture
def tmp_agents_dir():
    with tempfile.TemporaryDirectory() as d:
        agents_dir = Path(d) / "agents"
        agents_dir.mkdir()
        (agents_dir / "existing-agent.md").write_text(
            '---\n'
            'name: existing-agent\n'
            'description: An existing test agent\n'
            'model: test-model\n'
            'tools: []\n'
            '---\n'
            '\n'
            'You are an existing test agent.\n'
        )
        yield agents_dir


@pytest.fixture
def registry(tmp_agents_dir):
    reg = AgentRegistry(tmp_agents_dir)
    reg.scan()
    return reg


# ---------------------------------------------------------------------------
# create_agent tests
# ---------------------------------------------------------------------------

class TestCreateAgent:
    def test_create_basic_agent(self, fake_mcp, tmp_agents_dir):
        from opensensa.framework_tools.create_agent import register
        register(fake_mcp, agents_directory=str(tmp_agents_dir))

        create_fn = fake_mcp.get_tool("create_agent")
        result = create_fn(
            name="new-agent",
            description="A brand new agent",
            system_prompt="You are a helpful assistant.",
        )

        assert result["status"] == "created"
        assert result["name"] == "new-agent"

        # Verify file exists and has correct content
        file_path = tmp_agents_dir / "new-agent.md"
        assert file_path.exists()
        content = file_path.read_text()
        assert "name: new-agent" in content
        assert "description: A brand new agent" in content
        assert "You are a helpful assistant." in content

    def test_create_agent_with_tools(self, fake_mcp, tmp_agents_dir):
        from opensensa.framework_tools.create_agent import register
        register(fake_mcp, agents_directory=str(tmp_agents_dir))

        create_fn = fake_mcp.get_tool("create_agent")
        result = create_fn(
            name="tool-agent",
            description="Agent with tools",
            system_prompt="You use tools.",
            tools=["csv_formatter", "add_numbers"],
        )

        assert result["status"] == "created"
        content = (tmp_agents_dir / "tool-agent.md").read_text()
        assert "csv_formatter" in content
        assert "add_numbers" in content

    def test_create_agent_duplicate_rejected(self, fake_mcp, tmp_agents_dir):
        from opensensa.framework_tools.create_agent import register
        register(fake_mcp, agents_directory=str(tmp_agents_dir))

        create_fn = fake_mcp.get_tool("create_agent")
        result = create_fn(
            name="existing-agent",
            description="Should fail",
            system_prompt="Nope",
        )

        assert "error" in result
        assert "already exists" in result["error"]

    def test_create_agent_sanitizes_bad_name(self, fake_mcp, tmp_agents_dir):
        from opensensa.framework_tools.create_agent import register
        register(fake_mcp, agents_directory=str(tmp_agents_dir))

        create_fn = fake_mcp.get_tool("create_agent")
        result = create_fn(
            name="My Cool Agent!",
            description="Sanitized name",
            system_prompt="Hello.",
        )

        assert result["status"] == "created"
        # Name should be sanitized to kebab-case
        assert re.match(r"^[a-z0-9-]+$", result["name"])

    def test_create_agent_rejects_very_short_name(self, fake_mcp, tmp_agents_dir):
        from opensensa.framework_tools.create_agent import register
        register(fake_mcp, agents_directory=str(tmp_agents_dir))

        create_fn = fake_mcp.get_tool("create_agent")
        result = create_fn(
            name="a",
            description="Too short",
            system_prompt="Fail.",
        )

        assert "error" in result

    def test_create_agent_no_directory_configured(self, fake_mcp):
        from opensensa.framework_tools.create_agent import register
        register(fake_mcp, agents_directory=None)

        create_fn = fake_mcp.get_tool("create_agent")
        result = create_fn(
            name="test",
            description="Should fail",
            system_prompt="No dir",
        )

        assert "error" in result
        assert "not configured" in result["error"]


# ---------------------------------------------------------------------------
# discover_agents tests
# ---------------------------------------------------------------------------

class TestDiscoverAgents:
    @pytest.mark.asyncio
    async def test_discover_local_agents(self, fake_mcp, registry):
        from opensensa.framework_tools.discover_agents import register
        register(
            fake_mcp,
            agent_registry=registry,
            remote_agents=None,
            local_base_url="http://localhost:8000",
        )

        discover_fn = fake_mcp.get_tool("discover_agents")
        agents = await discover_fn()

        assert len(agents) >= 1
        local = [a for a in agents if a["source"] == "local"]
        assert len(local) >= 1
        assert local[0]["name"] == "existing-agent"
        assert local[0]["url"] == "http://localhost:8000/agents/existing-agent"

    @pytest.mark.asyncio
    async def test_discover_no_agents(self, fake_mcp):
        from opensensa.framework_tools.discover_agents import register
        register(fake_mcp, agent_registry=None, remote_agents=None)

        discover_fn = fake_mcp.get_tool("discover_agents")
        agents = await discover_fn()
        assert agents == []

    @pytest.mark.asyncio
    async def test_discover_remote_agent_failure(self, fake_mcp, registry):
        """Remote agent that can't be reached should still return an entry."""
        from opensensa.framework_tools.discover_agents import register
        register(
            fake_mcp,
            agent_registry=registry,
            remote_agents=[{"url": "http://unreachable.local:9999"}],
            local_base_url="http://localhost:8000",
        )

        discover_fn = fake_mcp.get_tool("discover_agents")
        agents = await discover_fn()

        remote = [a for a in agents if a["source"] == "remote"]
        assert len(remote) == 1
        assert "unreachable" in remote[0]["name"]


# ---------------------------------------------------------------------------
# send_to_agent tests
# ---------------------------------------------------------------------------

class TestSendToAgent:
    @pytest.mark.asyncio
    async def test_depth_limit_enforced(self, fake_mcp):
        from opensensa.framework_tools.send_to_agent import register, MAX_A2A_DEPTH
        register(fake_mcp)

        send_fn = fake_mcp.get_tool("send_to_agent")
        result = await send_fn(
            agent_url="http://localhost:9000",
            message="Hello",
            current_depth=MAX_A2A_DEPTH,
        )

        assert result["status"] == "error"
        assert "depth limit" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_depth_below_limit_proceeds(self, fake_mcp):
        """Depth below limit should attempt the request (will fail on connection)."""
        from opensensa.framework_tools.send_to_agent import register
        register(fake_mcp)

        send_fn = fake_mcp.get_tool("send_to_agent")
        result = await send_fn(
            agent_url="http://127.0.0.1:1",  # unreachable
            message="Hello",
            current_depth=0,
        )

        # Should get a connection error, not a depth error
        assert result["status"] == "error"
        assert "depth limit" not in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_timeout_handling(self, fake_mcp):
        """Timeout should return a clean error."""
        from opensensa.framework_tools.send_to_agent import register
        register(fake_mcp)

        send_fn = fake_mcp.get_tool("send_to_agent")
        # Use unreachable address — will either timeout or connection error
        result = await send_fn(
            agent_url="http://192.0.2.1",  # TEST-NET, guaranteed unroutable
            message="Hello",
        )

        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# list_tools tests
# ---------------------------------------------------------------------------

class TestListTools:
    def test_list_tools_with_logged_mcp(self):
        """list_tools should return registered tool metadata from LoggedMCP."""
        from opensensa.utils.logging import LoggedMCP
        from mcp.server.fastmcp import FastMCP
        from opensensa.framework_tools.list_tools import register

        raw_mcp = FastMCP("test", host="127.0.0.1", port=18001)
        mcp = LoggedMCP(raw_mcp, enable_logging=False)

        # Register a dummy tool
        @mcp.tool(title="Dummy Tool", description="A test tool", tags=["test"])
        def dummy_tool(x: str) -> str:
            return x

        # Register list_tools
        register(mcp)

        # Verify registered_tools tracks both tools
        tools = mcp.registered_tools
        assert len(tools) >= 2  # Dummy Tool + List Tools
        assert "Dummy Tool" in tools
        assert tools["Dummy Tool"]["function"] == "dummy_tool"
        assert tools["Dummy Tool"]["description"] == "A test tool"

    def test_list_tools_with_fake_mcp(self, fake_mcp):
        """list_tools with a basic MCP should return even if introspection limited."""
        from opensensa.framework_tools.list_tools import register
        register(fake_mcp)

        list_fn = fake_mcp.get_tool("list_tools")
        result = list_fn()

        assert isinstance(result, list)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# delegate tests
# ---------------------------------------------------------------------------

class TestDelegate:
    """Tests for the native delegate FunctionTool (A2A, not MCP)."""

    def _make_agent_def(self, sub_agents=None):
        """Create a minimal AgentDefinition-like object for testing."""
        from opensensa.orchestrator.agent_registry import AgentDefinition
        return AgentDefinition(
            name="caller-agent",
            description="test",
            system_prompt="test",
            model="test-model",
            tools=[],
            sub_agents=sub_agents or [],
            source_file=None,
        )

    @pytest.mark.asyncio
    async def test_delegate_depth_limit(self, registry):
        from opensensa.framework_tools.delegate import _delegate_impl, MAX_DELEGATION_DEPTH

        result_json = await _delegate_impl(
            agent_name="existing-agent",
            message="Hello",
            allowed_sub_agents=["existing-agent"],
            agent_registry=registry,
            local_base_url="http://localhost:8000",
            current_depth=MAX_DELEGATION_DEPTH,
        )

        import json
        result = json.loads(result_json)
        assert result["status"] == "error"
        assert "depth limit" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_delegate_unknown_agent(self, registry):
        from opensensa.framework_tools.delegate import _delegate_impl

        result_json = await _delegate_impl(
            agent_name="nonexistent-agent",
            message="Hello",
            allowed_sub_agents=["nonexistent-agent"],
            agent_registry=registry,
            local_base_url="http://localhost:8000",
        )

        import json
        result = json.loads(result_json)
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_delegate_rejects_unlisted_agent(self, registry):
        """Delegation to an agent not in sub_agents should be rejected."""
        from opensensa.framework_tools.delegate import _delegate_impl

        result_json = await _delegate_impl(
            agent_name="existing-agent",
            message="Hello",
            allowed_sub_agents=["some-other-agent"],
            agent_registry=registry,
            local_base_url="http://localhost:8000",
        )

        import json
        result = json.loads(result_json)
        assert result["status"] == "error"
        assert "not in your sub_agents" in result["error"]

    @pytest.mark.asyncio
    async def test_delegate_resolves_local_agent(self, registry):
        """Delegation to a known local agent should attempt the A2A request (will fail on connection)."""
        from opensensa.framework_tools.delegate import _delegate_impl

        result_json = await _delegate_impl(
            agent_name="existing-agent",
            message="Hello",
            allowed_sub_agents=["existing-agent"],
            agent_registry=registry,
            local_base_url="http://127.0.0.1:1",
            current_depth=0,
        )

        import json
        result = json.loads(result_json)
        # Should get a connection error, not a "not found" error
        assert result["status"] == "error"
        assert "not found" not in result["error"].lower()

    def test_build_delegate_tool_returns_function_tool(self):
        """build_delegate_tool should return a FunctionTool with correct metadata."""
        from opensensa.framework_tools.delegate import build_delegate_tool
        from agents import FunctionTool

        agent_def = self._make_agent_def(sub_agents=["analyst", "writer"])
        tool = build_delegate_tool(agent_def)

        assert isinstance(tool, FunctionTool)
        assert tool.name == "delegate"
        assert "analyst" in tool.description
        assert "writer" in tool.description


# ---------------------------------------------------------------------------
# sub_agents in AgentDefinition tests
# ---------------------------------------------------------------------------

class TestSubAgentsParsing:
    def test_sub_agents_parsed_from_frontmatter(self):
        """sub_agents field should be parsed from agent .md frontmatter."""
        from opensensa.orchestrator.agent_registry import AgentDefinition

        with tempfile.TemporaryDirectory() as d:
            agent_file = Path(d) / "test-agent.md"
            agent_file.write_text(
                '---\n'
                'name: test-agent\n'
                'description: Test agent with sub-agents\n'
                'model: test-model\n'
                'tools:\n'
                '  - csv_formatter\n'
                'sub_agents:\n'
                '  - data-analyst\n'
                '  - statistician\n'
                '---\n'
                '\n'
                'You are a test agent.\n'
            )

            defn = AgentDefinition.from_file(agent_file)
            assert defn.sub_agents == ["data-analyst", "statistician"]

    def test_sub_agents_defaults_to_empty(self):
        """Agents without sub_agents should have an empty list."""
        from opensensa.orchestrator.agent_registry import AgentDefinition

        with tempfile.TemporaryDirectory() as d:
            agent_file = Path(d) / "simple.md"
            agent_file.write_text(
                '---\n'
                'name: simple\n'
                'description: Simple agent\n'
                '---\n'
                '\n'
                'You are simple.\n'
            )

            defn = AgentDefinition.from_file(agent_file)
            assert defn.sub_agents == []
