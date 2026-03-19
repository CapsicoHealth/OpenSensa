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

"""Tests for Phase 6 — A2A executor and server integration.

Tests the full A2A pipeline:
  - FrameworkAgentExecutor with a2a-sdk types
  - Orchestrator server with real A2A endpoints
  - Agent Card generation via a2a-sdk types
  - JSON-RPC SendMessage processing
"""

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensensa.config import AppConfig, ModelsConfig, ModelConfig, ServerConfig, AgentsConfig, ToolsConfig, LoggingConfig
from opensensa.orchestrator.agent_registry import AgentRegistry, AgentDefinition
from opensensa.orchestrator.server import create_orchestrator_app
from opensensa.a2a.agent_card import build_agent_card


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_agents_dir():
    """Create a temp directory with a test agent .md file."""
    with tempfile.TemporaryDirectory() as d:
        agents_dir = Path(d) / "agents"
        agents_dir.mkdir()
        (agents_dir / "test-agent.md").write_text(
            '---\n'
            'name: test-agent\n'
            'description: A simple test agent for integration tests\n'
            'model: test-model\n'
            'tools: []\n'
            'skills:\n'
            '  - id: test-skill\n'
            '    name: Test Skill\n'
            '    description: A test skill for validation\n'
            '    tags: [test, validation]\n'
            '    examples:\n'
            '      - "Run a test"\n'
            'input_modes: ["text/plain"]\n'
            'output_modes: ["text/plain", "application/json"]\n'
            '---\n'
            '\n'
            '# Test Agent\n'
            '\n'
            'You are a test agent that echoes inputs.\n'
        )
        yield agents_dir


@pytest.fixture
def config_with_model(tmp_agents_dir):
    """Config with a model registry entry (model won't actually connect)."""
    return AppConfig(
        models=ModelsConfig(
            default="test-model",
            registry={
                "test-model": ModelConfig(
                    base_url="http://localhost:11434/v1",
                    api_key="test-key",
                    model_name="test-llm",
                ),
            },
        ),
        server=ServerConfig(host="127.0.0.1", orchestrator_port=8000, mcp_port=8001),
        agents=AgentsConfig(directory=str(tmp_agents_dir)),
        tools=ToolsConfig(directory=str(tmp_agents_dir.parent / "tools")),
        logging=LoggingConfig(level="warning"),
    )


@pytest.fixture
def registry(tmp_agents_dir):
    """Agent registry pointing at test agents."""
    reg = AgentRegistry(tmp_agents_dir)
    reg.scan()
    return reg


@pytest.fixture
def app(config_with_model, registry):
    """FastAPI app with real A2A wiring."""
    return create_orchestrator_app(config_with_model, registry)


@pytest.fixture
def client(app):
    """TestClient for the orchestrator app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Agent Card tests (using a2a-sdk types)
# ---------------------------------------------------------------------------

class TestAgentCard:
    def test_build_single_agent_card(self, registry):
        agent_def = registry.get("test-agent")
        assert agent_def is not None

        card = build_agent_card(agent_def, "http://localhost:8000")

        # Verify it's an a2a-sdk AgentCard (Pydantic model)
        from a2a.types import AgentCard
        assert isinstance(card, AgentCard)
        assert card.name == "test-agent"
        assert card.description == "A simple test agent for integration tests"
        assert card.url == "http://localhost:8000/agents/test-agent"
        assert card.version == "1.0.0"
        assert card.capabilities.streaming is True
        assert card.capabilities.push_notifications is False
        assert len(card.skills) == 1
        assert card.skills[0].id == "test-skill"
        assert card.skills[0].name == "Test Skill"
        assert "test" in card.skills[0].tags
        assert "text/plain" in card.default_input_modes
        assert "application/json" in card.default_output_modes

    def test_agent_card_per_agent(self, registry):
        """Each agent should get a card with URL pointing to its sub-app."""
        agents = registry.list_agents()
        for agent_def in agents:
            card = build_agent_card(agent_def, "http://localhost:8000")
            assert card.url == f"http://localhost:8000/agents/{agent_def.name}"
            assert len(card.skills) >= 1

    def test_agent_card_serializes_to_json(self, registry):
        agent_def = registry.get("test-agent")
        card = build_agent_card(agent_def, "http://localhost:8000")

        # Should be serializable via Pydantic
        card_json = card.model_dump(mode="json", exclude_none=True)
        assert card_json["name"] == "test-agent"
        assert isinstance(card_json["skills"], list)

    def test_default_skill_when_none_defined(self, tmp_agents_dir):
        """Agent with no skills gets a default skill from its name/description."""
        (tmp_agents_dir / "no-skills.md").write_text(
            '---\n'
            'name: bare-agent\n'
            'description: Agent with no skills defined\n'
            'model: test-model\n'
            'tools: []\n'
            '---\n'
            '\n'
            'You are a bare agent.\n'
        )
        reg = AgentRegistry(tmp_agents_dir)
        agent_def = reg.get("bare-agent")
        card = build_agent_card(agent_def, "http://localhost:8000")

        assert len(card.skills) == 1
        assert card.skills[0].id == "bare-agent"
        assert card.skills[0].name == "bare-agent"
        assert card.url == "http://localhost:8000/agents/bare-agent"


# ---------------------------------------------------------------------------
# Orchestrator server endpoint tests
# ---------------------------------------------------------------------------

class TestOrchestratorEndpoints:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "test-agent" in data["agents"]

    def test_agent_card_endpoint(self, client):
        resp = client.get("/agents/test-agent/.well-known/agent-card.json")
        assert resp.status_code == 200
        card = resp.json()
        assert card["name"] == "test-agent"
        assert isinstance(card["skills"], list)
        assert len(card["skills"]) >= 1
        assert card["capabilities"]["streaming"] is True

    def test_agents_list(self, client):
        resp = client.get("/agents")
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) >= 1
        assert agents[0]["name"] == "test-agent"
        assert "url" in agents[0]  # Per-agent URL should be included

    def test_a2a_send_message(self, client):
        """SendMessage should reach the executor and return a Task (even if LLM fails)."""
        payload = {
            "jsonrpc": "2.0",
            "id": "test-req-1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Hello agent"}],
                    "messageId": "msg-test-1",
                }
            }
        }
        resp = client.post("/agents/test-agent/", json=payload)
        assert resp.status_code == 200
        result = resp.json()

        # Should be a valid JSON-RPC response
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == "test-req-1"

        # Should have a result (Task) — it may be failed (no real LLM) but it's a proper Task
        task = result.get("result")
        assert task is not None
        assert "id" in task  # Task ID
        assert "status" in task
        # The task should have reached the executor (failed because no real LLM is connected)
        # The status.state should be "failed" since the model endpoint is unreachable
        assert task["status"]["state"] in ("failed", "completed", "working")

    def test_a2a_send_message_empty_text(self, client):
        """SendMessage with empty text should get a failed status."""
        payload = {
            "jsonrpc": "2.0",
            "id": "test-req-2",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": ""}],
                    "messageId": "msg-test-2",
                }
            }
        }
        resp = client.post("/agents/test-agent/", json=payload)
        assert resp.status_code == 200
        result = resp.json()
        task = result.get("result")
        assert task is not None
        assert task["status"]["state"] == "failed"

    def test_a2a_invalid_method(self, client):
        """Unknown JSON-RPC method should return an error."""
        payload = {
            "jsonrpc": "2.0",
            "id": "test-req-3",
            "method": "nonexistent/method",
            "params": {}
        }
        resp = client.post("/agents/test-agent/", json=payload)
        assert resp.status_code == 200
        result = resp.json()
        assert "error" in result


# ---------------------------------------------------------------------------
# Executor unit tests
# ---------------------------------------------------------------------------

class TestFrameworkAgentExecutor:
    def test_executor_is_a2a_compatible(self, config_with_model, registry):
        """Executor should implement the a2a-sdk AgentExecutor interface."""
        from opensensa.a2a.executor import FrameworkAgentExecutor
        from a2a.server.agent_execution.agent_executor import AgentExecutor

        executor = FrameworkAgentExecutor(
            agent_name="test-agent",
            agent_registry=registry,
            config=config_with_model,
        )
        assert isinstance(executor, AgentExecutor)

    def test_executor_bound_to_agent(self, config_with_model, registry):
        """Executor should be bound to its agent name."""
        from opensensa.a2a.executor import FrameworkAgentExecutor

        executor = FrameworkAgentExecutor(
            agent_name="test-agent",
            agent_registry=registry,
            config=config_with_model,
        )
        assert executor._agent_name == "test-agent"


# ---------------------------------------------------------------------------
# Task store tests
# ---------------------------------------------------------------------------

class TestTaskStore:
    @pytest.mark.asyncio
    async def test_inmemory_task_store_save_and_get(self):
        """InMemoryTaskStore from a2a-sdk should work."""
        from opensensa.a2a.task_store import InMemoryTaskStore
        from a2a.types import Task, TaskState, TaskStatus, Message, Role, TextPart

        store = InMemoryTaskStore()

        task = Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.submitted),
            kind="task",
        )
        await store.save(task)

        retrieved = await store.get("task-1")
        assert retrieved is not None
        assert retrieved.id == "task-1"
        assert retrieved.status.state == TaskState.submitted
