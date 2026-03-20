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

"""Agent builder — constructs OpenAI Agents SDK Agent objects from AgentDefinitions.

Wires up MCP tool connections, model selection, and system prompts.
Inter-agent delegation is handled via a native ``FunctionTool`` that calls
sub-agents directly over A2A — bypassing MCP entirely (MCP is for tools,
A2A is for agent-to-agent communication).
"""

import logging
from contextlib import AsyncExitStack
from typing import Any, Optional

from opensensa.config import AppConfig
from opensensa.orchestrator.agent_registry import AgentDefinition
from opensensa.orchestrator.models import create_model_from_ref

logger = logging.getLogger("opensensa.orchestrator")


async def build_agent(
    agent_def: AgentDefinition,
    config: AppConfig,
    mcp_server_url: str = "http://localhost:8001/mcp",
    exit_stack: Optional[AsyncExitStack] = None,
    mcp_headers: Optional[dict[str, str]] = None,
    agent_registry=None,
    remote_agents: list[dict] | None = None,
    call_graph=None,
    client_request_id: Optional[str] = None,
    context_headers: Optional[dict[str, str]] = None,
    current_depth: int = 0,
) -> Any:
    """Build an OpenAI Agents SDK Agent from an AgentDefinition.

    Args:
        agent_def: Parsed agent definition from .md file.
        config: OpenSensa configuration for model resolution.
        mcp_server_url: URL of the MCP tool server.
        exit_stack: AsyncExitStack for managing MCP connection lifecycle.
        mcp_headers: Headers to pass to MCP server (for context injection).
        agent_registry: AgentRegistry for resolving sub-agent names (delegation).
        remote_agents: Remote agent entries for delegation.
        client_request_id: Original client JSON-RPC id, propagated through
            all delegation hops for session tracking.
        context_headers: Context headers from the client request, cascaded
            through delegations so sub-agents and tools share the same context.
        current_depth: Current delegation depth (for depth limit enforcement).

    Returns:
        An Agent instance ready for Runner.run().
    """
    from agents import Agent
    from agents.mcp import MCPServerStreamableHttp

    # Resolve model
    model = create_model_from_ref(config, agent_def.model)

    # Build MCP server connection with runtime headers
    headers = {}
    if mcp_headers:
        headers.update(mcp_headers)

    # MCP is only needed for tools — delegation uses native function tools
    mcp_servers = []
    if agent_def.tools:
        mcp_server = MCPServerStreamableHttp(
            params={
                "url": mcp_server_url,
                "timeout": 30,           # tool calls like document_search can take >5s
                **({"headers": headers} if headers else {}),
            },
        )
        mcp_servers.append(mcp_server)

        # If we have an exit stack, enter the MCP server context
        if exit_stack:
            try:
                await exit_stack.enter_async_context(mcp_server)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to connect to MCP server at {mcp_server_url}: {exc}. "
                    "Verify the URL is correct and the server is running."
                ) from exc

    # Build tool filter if agent specifies specific tools
    tool_filter = None
    if agent_def.tools:
        allowed = set(agent_def.tools)

        def _tool_filter(tool) -> bool:
            """Only allow tools listed in the agent definition."""
            name = getattr(tool, "name", None) or getattr(tool, "function", {}).get("name", "")
            return name in allowed

        # Use static tool filter from agents SDK if available
        try:
            from agents.mcp import create_static_tool_filter
            tool_filter = create_static_tool_filter(list(allowed))
        except ImportError:
            tool_filter = _tool_filter

    # Build native function tools (non-MCP)
    native_tools: list[Any] = []

    # Always attach the delegate tool as a native FunctionTool.
    # When the agent declares sub_agents, delegation is restricted to that
    # allowlist.  Otherwise, the agent can delegate to any agent by name
    # (via registry) or URL (e.g. discovered via discover_agents).
    # Delegation calls sub-agents over A2A directly — no MCP timeout issues.
    from opensensa.framework_tools.delegate import build_delegate_tool

    delegate_tool = build_delegate_tool(
        agent_def,
        agent_registry=agent_registry,
        local_base_url=config.server.local_base_url,
        remote_agents=remote_agents,
        call_graph=call_graph,
        client_request_id=client_request_id,
        context_headers=context_headers,
        current_depth=current_depth,
    )
    native_tools.append(delegate_tool)

    # Build agent
    agent = Agent(
        name=agent_def.name,
        instructions=agent_def.system_prompt,
        model=model,
        tools=native_tools,
        mcp_servers=mcp_servers,
        mcp_config={
            "tool_filter": tool_filter,
        } if tool_filter else {},
    )

    logger.info(f"Built agent: {agent_def.name} (model={agent_def.model}, tools={agent_def.tools}, sub_agents={agent_def.sub_agents})")
    return agent
