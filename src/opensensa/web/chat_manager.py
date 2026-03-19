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

"""Web chat session manager — manages concurrent browser chat sessions.

Each session holds conversation history, an agent definition, and references
to the shared MCP / A2A servers (no per-session subprocess spawning).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import AsyncExitStack
from typing import Any, AsyncGenerator

from opensensa.config import AppConfig
from opensensa.orchestrator.agent_registry import AgentDefinition, AgentRegistry
from opensensa.web.call_graph import WebCallGraph

logger = logging.getLogger("opensensa.web")


class ChatSession:
    """One browser chat session with a single agent."""

    def __init__(
        self,
        session_id: str,
        agent_def: AgentDefinition,
        config: AppConfig,
        registry: AgentRegistry,
        mcp_server_url: str,
    ) -> None:
        self.session_id = session_id
        self.agent_def = agent_def
        self.config = config
        self.registry = registry
        self.mcp_server_url = mcp_server_url
        self.conversation_history: list[Any] = []
        self.created_at: float = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_name": self.agent_def.name,
            "history_length": len(self.conversation_history),
            "created_at": self.created_at,
        }


def _make_web_hooks(call_graph: WebCallGraph):
    """Create RunHooks that push events into a WebCallGraph.

    Returns None if the agents SDK doesn't expose RunHooks.
    """
    try:
        from agents import RunHooks  # type: ignore[attr-defined]

        class _WebHooks(RunHooks):
            def __init__(self, graph: WebCallGraph):
                self._graph = graph
                self._llm_start_time: float = 0.0
                self._tool_start_times: dict[str, float] = {}
                self._agent_start_time: float = 0.0

            async def on_llm_start(self, context, agent, system_prompt, input_items):
                self._llm_start_time = time.monotonic()
                agent_name = getattr(agent, "name", str(agent))
                self._graph.start_llm(agent_name)

            async def on_llm_end(self, context, agent, response):
                duration_ms = int((time.monotonic() - self._llm_start_time) * 1000)
                usage = getattr(response, "usage", None)
                total_tokens = 0
                if usage:
                    total_tokens = getattr(usage, "total_tokens", 0)
                agent_name = getattr(agent, "name", str(agent))
                self._graph.end_llm(
                    agent_name=agent_name,
                    duration_ms=duration_ms,
                    tokens=total_tokens,
                )

            async def on_tool_start(self, context, agent, tool):
                name = getattr(tool, "name", None) or str(tool)
                self._tool_start_times[name] = time.monotonic()
                self._graph.start_tool(name)

            async def on_tool_end(self, context, agent, tool, result):
                name = getattr(tool, "name", None) or str(tool)
                duration_ms = int(
                    (time.monotonic() - self._tool_start_times.pop(name, time.monotonic())) * 1000
                )
                text = str(result) if result else ""
                self._graph.end_tool(name, duration_ms=duration_ms, result=text)

            async def on_agent_start(self, context, agent):
                self._agent_start_time = time.monotonic()
                agent_name = getattr(agent, "name", str(agent))
                self._graph.start_agent(agent_name)

            async def on_agent_end(self, context, agent, output):
                duration_ms = int((time.monotonic() - self._agent_start_time) * 1000)
                agent_name = getattr(agent, "name", str(agent))
                self._graph.end_agent(agent_name, duration_ms=duration_ms)

            async def on_handoff(self, context, from_agent, to_agent):
                from_name = getattr(from_agent, "name", str(from_agent))
                to_name = getattr(to_agent, "name", str(to_agent))
                self._graph.start_delegation(from_name, to_name)

        return _WebHooks(graph=call_graph)
    except ImportError:
        return None
    except Exception:
        logger.warning("Failed to create web RunHooks", exc_info=True)
        return None


class ChatManager:
    """Manages multiple concurrent browser chat sessions."""

    def __init__(
        self,
        config: AppConfig,
        registry: AgentRegistry,
        mcp_server_url: str,
    ) -> None:
        self.config = config
        self.registry = registry
        self.mcp_server_url = mcp_server_url
        self._sessions: dict[str, ChatSession] = {}

    def create_session(self, agent_name: str) -> ChatSession:
        """Create a new chat session for the given agent."""
        agent_def = self.registry.get(agent_name)
        if not agent_def:
            raise ValueError(f"Agent '{agent_name}' not found")

        session_id = str(uuid.uuid4())[:8]
        session = ChatSession(
            session_id=session_id,
            agent_def=agent_def,
            config=self.config,
            registry=self.registry,
            mcp_server_url=self.mcp_server_url,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> list[dict]:
        return [s.to_dict() for s in self._sessions.values()]

    async def send_message(
        self,
        session_id: str,
        user_input: str,
        *,
        context_headers: dict[str, str] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Run one agent turn and yield SSE events.

        This is an async generator — the SSE endpoint iterates it.

        Args:
            context_headers: Optional per-request headers extracted from the
                client HTTP request (e.g. X-Document-URL, X-Project).  These
                override the static defaults from the agent definition and are
                forwarded to MCP tool servers.
        """
        session = self._sessions.get(session_id)
        if not session:
            yield f'data: {{"event": "turn_error", "error": "Session not found"}}\n\n'
            return

        # Create WebCallGraph + hooks for this turn
        call_graph = WebCallGraph(agent_name=session.agent_def.name)
        hooks = _make_web_hooks(call_graph)

        # Start the agent turn in a background task
        agent_task = asyncio.create_task(
            self._run_agent_turn(session, user_input, call_graph, hooks, context_headers=context_headers)
        )

        # Stream events from the call graph
        async for event_str in call_graph.events():
            yield event_str

        # Ensure the task is done (it should be — call_graph.finish() was called)
        try:
            await agent_task
        except Exception:
            pass  # errors already emitted via call_graph.error()

    async def _run_agent_turn(
        self,
        session: ChatSession,
        user_input: str,
        call_graph: WebCallGraph,
        hooks: Any,
        *,
        context_headers: dict[str, str] | None = None,
    ) -> None:
        """Execute one agent turn. Pushes events to call_graph, finishes with response or error."""
        try:
            from agents import Runner
            from opensensa.orchestrator.agent_builder import build_agent

            async with AsyncExitStack() as exit_stack:
                # Infrastructure headers required by the MCP tool server
                # (X-Conversation-Id is mandatory for tool logging).
                mcp_headers: dict[str, str] = {
                    "X-Conversation-Id": session.session_id,
                    "X-Agent-Id": session.agent_def.name,
                    "X-Agent-Depth": "0",
                }
                # Per-request context headers from the client (e.g. X-Document-URL)
                if context_headers:
                    mcp_headers.update(context_headers)
                logger.info(
                    "_run_agent_turn: agent=%s context_headers=%s mcp_headers=%s",
                    session.agent_def.name,
                    context_headers,
                    mcp_headers,
                )

                remote_agents = [
                    {"url": ra.url, "name": getattr(ra, "name", "")}
                    for ra in session.config.remote_agents
                ]

                agent = await build_agent(
                    agent_def=session.agent_def,
                    config=session.config,
                    mcp_server_url=session.mcp_server_url,
                    exit_stack=exit_stack,
                    mcp_headers=mcp_headers or None,
                    agent_registry=session.registry,
                    remote_agents=remote_agents or None,
                    call_graph=call_graph,
                )

                # Build input
                if session.conversation_history:
                    input_items = session.conversation_history.copy()
                    input_items.append({"role": "user", "content": user_input})
                    run_input: Any = input_items
                else:
                    run_input = user_input

                result = await asyncio.wait_for(
                    Runner.run(
                        starting_agent=agent,
                        input=run_input,
                        hooks=hooks,
                        max_turns=25,
                    ),
                    timeout=300.0,
                )

                # Persist history
                session.conversation_history = result.to_input_list()

                # Extract response text
                response = ""
                if result.final_output:
                    response = str(result.final_output)
                elif result.new_items:
                    parts = []
                    for item in result.new_items:
                        for attr in ("text", "output"):
                            if hasattr(item, attr):
                                parts.append(str(getattr(item, attr)))
                                break
                    response = "\n".join(parts) if parts else "Agent completed with no output."
                else:
                    response = "Agent completed with no output."

                call_graph.finish(response=response)

        except asyncio.TimeoutError:
            call_graph.error("Request timed out after 5 minutes.")
        except Exception as exc:
            logger.error("Agent turn failed", exc_info=True)
            msg = str(exc).strip()
            lower = msg.lower()

            if any(kw in lower for kw in ("401", "unauthorized", "api key", "authentication")):
                call_graph.error("Authentication failed — check your API key.")
            elif any(kw in lower for kw in ("429", "rate limit", "rate_limit", "quota")):
                call_graph.error("Rate-limited — wait a moment and try again.")
            elif any(kw in lower for kw in ("model_not_found", "model not found", "does not exist")):
                call_graph.error("Model not found — check the model name in your agent config.")
            elif any(kw in lower for kw in ("failed to connect to mcp", "session terminated", "mcp")):
                call_graph.error("MCP connection failed — check the MCP server URL and ensure it is running.")
            elif any(kw in lower for kw in ("connection", "timed out", "timeout", "unreachable")):
                call_graph.error("Connection error — unable to reach the LLM provider.")
            else:
                call_graph.error(msg[:300] if len(msg) > 300 else msg)
