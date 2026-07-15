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

"""Framework tool: delegate — native function tool for agent-to-agent delegation.

Delegation is an A2A (agent-to-agent) operation, not a tool operation.
This module builds a native ``FunctionTool`` (from the OpenAI Agents SDK)
that calls sub-agents directly over A2A — bypassing MCP entirely.

This avoids MCP's short tool-call timeout (5 s default) which is inappropriate
for delegation calls that involve full LLM round-trips on the target agent.

Usage in ``agent_builder.py``::

    from opensensa.framework_tools.delegate import build_delegate_tool
    tool = build_delegate_tool(agent_def, registry, ...)
    Agent(..., tools=[tool, ...])
"""

import json
import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger("opensensa.framework_tools")

# Maximum delegation depth to prevent infinite loops
MAX_DELEGATION_DEPTH = 5

# Header used to propagate current delegation depth
_DEPTH_HEADER = "X-A2A-Depth"

# Timeout for the A2A HTTP call (seconds) — generous because the sub-agent
# runs a full LLM turn which can take 30-60 s.
_A2A_TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# Async-aware delegation event helpers
# ---------------------------------------------------------------------------

async def _notify_delegation_start(
    call_graph, from_agent: str, to_agent: str, *, message: str = ""
) -> None:
    """Emit a delegation_start event, using async path when available."""
    if call_graph is None:
        return
    if hasattr(call_graph, "emit_delegation_start"):
        await call_graph.emit_delegation_start(
            from_agent, to_agent, message=message
        )
    else:
        call_graph.start_delegation(from_agent, to_agent, message=message)


async def _notify_delegation_end(
    call_graph, to_agent: str, *, response: str = ""
) -> None:
    """Emit a delegation_end event, using async path when available."""
    if call_graph is None:
        return
    if hasattr(call_graph, "emit_delegation_end"):
        await call_graph.emit_delegation_end(to_agent, response=response)
    else:
        call_graph.end_delegation(to_agent, response=response)


def _extract_response_text(result: dict) -> str:
    """Extract a human-readable response string from an A2A task result.

    When the sub-agent streams its response, each token/chunk arrives as a
    separate ``artifact-update`` SSE event (with ``append: true``).  We
    concatenate all non-trace text parts to reconstruct the full response.
    """
    parts: list[str] = []
    for artifact in result.get("artifacts", []):
        name = artifact.get("name", "")
        if name.endswith("-execution-trace"):
            continue
        for part in artifact.get("parts", []):
            text = part.get("text", "")
            if text:
                parts.append(text)
    return "".join(parts)


def _resolve_agent_url(
    agent_name: str,
    *,
    agent_registry=None,
    local_base_url: str = "http://localhost:8000",
    remote_agents: list[dict] | None = None,
) -> str | None:
    """Resolve an agent name to its A2A endpoint URL.

    Checks local agents first, then remote agents.
    """
    if agent_registry:
        defn = agent_registry.get(agent_name)
        if defn is not None:
            return f"{local_base_url.rstrip('/')}/agents/{agent_name}"

    for entry in (remote_agents or []):
        url = entry.get("url", "").rstrip("/")
        name = entry.get("name", "")
        if name == agent_name and url:
            return url

    return None


async def _try_stream_delegation(
    a2a_endpoint: str,
    params: dict,
    headers: dict,
    *,
    call_graph=None,
    client_request_id: str | None = None,
) -> tuple[list[dict], dict]:
    """Attempt a streaming A2A delegation (``message/stream``).

    Uses ``httpx_sse`` (the same SSE parser the a2a-sdk uses internally)
    for reliable server-sent event parsing.  Falls through on any
    failure — caller should fall back to synchronous ``message/send``.

    Returns ``(tools_used, task_result)`` where *tools_used* is the
    sub-agent's execution trace and *task_result* is a dict with at
    least an ``artifacts`` key.
    """
    from httpx_sse import aconnect_sse

    payload = {
        "jsonrpc": "2.0",
        "id": client_request_id or str(uuid.uuid4()),
        "method": "message/stream",
        "params": params,
    }

    tools_used: list[dict] = []
    artifacts: list[dict] = []

    async with httpx.AsyncClient(timeout=_A2A_TIMEOUT) as client:
        async with aconnect_sse(
            client, "POST", a2a_endpoint, json=payload, headers=headers,
        ) as event_source:
            event_source.response.raise_for_status()
            async for sse in event_source.aiter_sse():
                if not sse.data:
                    continue
                try:
                    event = json.loads(sse.data)
                except (ValueError, TypeError):
                    continue

                result = event.get("result", {})
                kind = result.get("kind", "")

                # ---- Real-time tool events from the sub-agent ----
                if kind == "status-update":
                    status_obj = result.get("status", {})
                    msg = status_obj.get("message", {})

                    # Try structured framework:* metadata first (new format),
                    # fall back to parsing __event__ from text (legacy).
                    msg_meta = msg.get("metadata") or {}
                    framework_event = msg_meta.get("framework:event")

                    if framework_event:
                        # ---- New: structured metadata path ----
                        tool = msg_meta.get("framework:tool", "")
                        logger.info(
                            f"_try_stream_delegation: received framework:event={framework_event} "
                            f"from sub-agent metadata (call_graph={'set' if call_graph else 'None'})"
                        )
                        if call_graph is not None:
                            if framework_event == "tool_start":
                                call_graph.add_delegation_sub_event(
                                    "tool_start", tool,
                                    agent_name=msg_meta.get("framework:agent"),
                                )
                            elif framework_event == "tool_end":
                                call_graph.add_delegation_sub_event(
                                    "tool_end", tool,
                                    agent_name=msg_meta.get("framework:agent"),
                                    tools_used=msg_meta.get("framework:tools_used"),
                                )
                            elif framework_event == "delegation_start":
                                await _notify_delegation_start(
                                    call_graph,
                                    msg_meta.get("framework:from_agent", ""),
                                    msg_meta.get("framework:to_agent", ""),
                                    message=msg_meta.get("framework:message", ""),
                                )
                            elif framework_event == "delegation_end":
                                await _notify_delegation_end(
                                    call_graph,
                                    msg_meta.get("framework:to_agent", ""),
                                    response=msg_meta.get("framework:response", ""),
                                )
                    else:
                        # ---- Legacy: parse __event__ from text parts ----
                        for part in msg.get("parts", []):
                            text = part.get("text", "")
                            if text.startswith('{"__event__"'):
                                try:
                                    evt = json.loads(text)
                                    etype = evt.get("__event__")
                                    tool = evt.get("tool", "")
                                    logger.info(
                                        f"_try_stream_delegation: received __event__={etype} "
                                        f"from sub-agent SSE (call_graph={'set' if call_graph else 'None'})"
                                    )
                                    if call_graph is None:
                                        continue
                                    if etype == "tool_start":
                                        call_graph.add_delegation_sub_event(
                                            "tool_start", tool,
                                            agent_name=evt.get("agent"),
                                        )
                                    elif etype == "tool_end":
                                        call_graph.add_delegation_sub_event(
                                            "tool_end", tool,
                                            agent_name=evt.get("agent"),
                                            tools_used=evt.get("tools_used"),
                                        )
                                    # -- Nested delegation events --
                                    elif etype == "delegation_start":
                                        await _notify_delegation_start(
                                            call_graph,
                                            evt.get("from_agent", ""),
                                            evt.get("to_agent", ""),
                                            message=evt.get("message", ""),
                                        )
                                    elif etype == "delegation_end":
                                        await _notify_delegation_end(
                                            call_graph,
                                            evt.get("to_agent", ""),
                                            response=evt.get("response", ""),
                                        )
                                except (ValueError, TypeError):
                                    pass

                # ---- Artifact updates ----
                elif kind == "artifact-update":
                    artifact = result.get("artifact", {})
                    artifacts.append(artifact)
                    aname = artifact.get("name", "")
                    if aname.endswith("-execution-trace"):
                        for part in artifact.get("parts", []):
                            if part.get("kind") == "data":
                                data = part.get("data", {})
                                tools_used = data.get("tools_used", [])

    return tools_used, {"artifacts": artifacts}


async def _run_ephemeral_in_process(
    agent_name: str,
    message: str,
    *,
    agent_registry,
    app_config,
    mcp_server_url: str,
    context_headers: dict[str, str] | None,
    remote_agents: list[dict] | None,
    call_graph,
    client_request_id: str | None,
    current_depth: int,
) -> str:
    """Run an ephemeral agent in-process instead of via an HTTP call.

    Ephemeral agents have no mounted sub-app, so delegating via HTTP would yield
    a 404.  Instead we build the agent directly with ``build_agent()`` and run it
    in the same process, reusing the same EphemeralRegistry so that nested
    ephemeral sub-agents of ephemeral sub-agents also take this path.
    """
    import time as _time
    from contextlib import AsyncExitStack
    from agents import Runner
    from opensensa.orchestrator.agent_builder import build_agent

    _start = _time.time()

    agent_def = agent_registry.get(agent_name)
    if agent_def is None:
        return json.dumps({
            "status": "error",
            "error": f"Ephemeral agent '{agent_name}' not found in registry.",
        })

    mcp_headers: dict[str, str] = {
        "X-Agent-Id": agent_name,
        "X-Agent-Depth": str(current_depth),
    }
    if context_headers:
        mcp_headers.update(context_headers)

    try:
        async with AsyncExitStack() as stack:
            agent = await build_agent(
                agent_def=agent_def,
                config=app_config,
                mcp_server_url=mcp_server_url,
                exit_stack=stack,
                mcp_headers=mcp_headers,
                agent_registry=agent_registry,
                remote_agents=remote_agents,
                call_graph=call_graph,
                client_request_id=client_request_id,
                context_headers=context_headers,
                current_depth=current_depth,
            )
            result = await Runner.run(
                agent,
                [{"role": "user", "content": message}],
            )
        final_text = str(result.final_output) if result.final_output else ""
        duration_ms = int((_time.time() - _start) * 1000)
        task_result = {
            "artifacts": [
                {
                    "name": f"{agent_name}-response",
                    "parts": [{"text": final_text}],
                }
            ]
        }
        # Structured telemetry log for ephemeral in-process delegations.
        # No HTTP handler exists for these, so no automatic agenticaccesslog row.
        logger.info(
            "EPHEMERAL_DELEGATION_COMPLETE agent=%s depth=%d duration_ms=%d "
            "status=success response_len=%d",
            agent_name, current_depth, duration_ms, len(final_text),
        )
        return json.dumps({"status": "success", "agent": agent_name, "result": task_result})
    except Exception as exc:
        duration_ms = int((_time.time() - _start) * 1000)
        logger.error(
            "EPHEMERAL_DELEGATION_COMPLETE agent=%s depth=%d duration_ms=%d "
            "status=error error=%s",
            agent_name, current_depth, duration_ms, exc,
        )
        return json.dumps({
            "status": "error",
            "error": f"In-process execution of '{agent_name}' failed: {exc}",
        })


async def _delegate_impl(
    message: str,
    *,
    agent_name: str | None = None,
    agent_url: str | None = None,
    allowed_sub_agents: list[str] | None = None,
    from_agent_name: str = "unknown",
    agent_registry=None,
    local_base_url: str = "http://localhost:8000",
    remote_agents: list[dict] | None = None,
    current_depth: int = 0,
    call_graph=None,
    client_request_id: str | None = None,
    context_headers: dict[str, str] | None = None,
    app_config=None,
    mcp_server_url: str | None = None,
) -> str:
    """Core delegation logic — sends an A2A request to another agent.

    Accepts either ``agent_name`` (resolved via registry) or ``agent_url``
    (used directly).  When ``agent_name`` is provided and the caller has a
    ``sub_agents`` allowlist, the name is validated against it.

    Returns a JSON string (the Agents SDK expects function tools to return str).
    """
    if not agent_name and not agent_url:
        return json.dumps({
            "status": "error",
            "error": "Either 'agent_name' or 'agent_url' must be provided.",
        })

    # When using name-based delegation with an allowlist, enforce it
    if agent_name and allowed_sub_agents and agent_name not in allowed_sub_agents:
        return json.dumps({
            "status": "error",
            "error": (
                f"Agent '{agent_name}' is not in your sub_agents list. "
                f"Allowed sub-agents: {allowed_sub_agents}"
            ),
        })

    # Enforce depth limit
    if current_depth >= MAX_DELEGATION_DEPTH:
        target = agent_name or agent_url
        logger.warning(
            f"Delegation depth limit reached ({current_depth}/{MAX_DELEGATION_DEPTH}). "
            f"Refusing to delegate to '{target}'."
        )
        return json.dumps({
            "status": "error",
            "error": (
                f"Delegation depth limit reached ({MAX_DELEGATION_DEPTH}). "
                "This prevents infinite agent-to-agent loops. "
                "Try handling this task directly instead of delegating."
            ),
        })

    # Resolve target — either from name or direct URL
    if agent_url:
        resolved_url = agent_url.rstrip("/")
        # Derive a display name from the URL if no name given
        if not agent_name:
            agent_name = resolved_url.rstrip("/").split("/")[-1] or "remote-agent"
    else:
        resolved_url_or_none = _resolve_agent_url(
            agent_name,
            agent_registry=agent_registry,
            local_base_url=local_base_url,
            remote_agents=remote_agents,
        )
        if not resolved_url_or_none:
            return json.dumps({
                "status": "error",
                "error": (
                    f"Agent '{agent_name}' not found. "
                    f"Make sure it exists as a local or remote agent, "
                    f"or provide an agent_url instead."
                ),
            })
        resolved_url = resolved_url_or_none

    # In-process shortcut: ephemeral agents have no mounted sub-app, so an
    # HTTP call to /agents/{name}/ would return 404. Run the agent directly
    # in-process using the same EphemeralRegistry so that nested ephemeral
    # sub-agents of ephemeral sub-agents also take this path recursively.
    if (
        agent_name
        and agent_url is None
        and app_config is not None
        and mcp_server_url is not None
        and hasattr(agent_registry, "is_ephemeral")
        and agent_registry.is_ephemeral(agent_name)
    ):
        logger.info("Delegating to ephemeral agent '%s' in-process (no HTTP)", agent_name)
        if call_graph is not None:
            call_graph.update_delegation_target(agent_name)
        await _notify_delegation_start(call_graph, from_agent_name, agent_name, message=message)
        result_json = await _run_ephemeral_in_process(
            agent_name,
            message,
            agent_registry=agent_registry,
            app_config=app_config,
            mcp_server_url=mcp_server_url,
            context_headers=context_headers,
            remote_agents=remote_agents,
            call_graph=call_graph,
            client_request_id=client_request_id,
            current_depth=current_depth + 1,
        )
        result_data = json.loads(result_json)
        delegate_response = (
            _extract_response_text(result_data.get("result", {}))
            if result_data.get("status") == "success"
            else ""
        )
        await _notify_delegation_end(call_graph, agent_name, response=delegate_response)
        return result_json

    # Build A2A request parameters
    a2a_endpoint = f"{resolved_url}/"

    # Immediately show the delegation target in the call graph
    if call_graph is not None:
        call_graph.update_delegation_target(agent_name)
    await _notify_delegation_start(
        call_graph, from_agent_name, agent_name, message=message
    )

    params: dict[str, Any] = {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": message}],
            "messageId": str(uuid.uuid4()),
        }
    }

    # Cascade context headers to sub-agent via A2A metadata so the
    # receiving executor can forward them to MCP tools and further
    # delegations — the same context the original client provided.
    if context_headers:
        params.setdefault("metadata", {})["context_headers"] = context_headers

    next_depth = current_depth + 1
    headers = {
        "Content-Type": "application/json",
        _DEPTH_HEADER: str(next_depth),
    }
    # Propagate the original client request id so every hop in the
    # delegation chain shares the same session identifier.
    if client_request_id:
        headers["X-A2A-Client-Request-Id"] = client_request_id

    # ---- Stream delegation via A2A message/stream ----
    try:
        stream_tools, stream_result = await _try_stream_delegation(
            a2a_endpoint, params, headers,
            call_graph=call_graph,
            client_request_id=client_request_id,
        )
        response: dict[str, Any] = {
            "status": "success",
            "agent": agent_name,
            "result": stream_result,
        }
        if stream_tools:
            response["tools_used"] = stream_tools
        delegate_response = _extract_response_text(stream_result)
        await _notify_delegation_end(
            call_graph, agent_name, response=delegate_response
        )
        return json.dumps(response)

    except httpx.TimeoutException:
        await _notify_delegation_end(
            call_graph, agent_name, response="Request timed out"
        )
        return json.dumps({
            "status": "error",
            "error": f"Request to agent '{agent_name}' timed out after {_A2A_TIMEOUT}s",
        })
    except Exception as e:
        logger.error(f"Delegation to '{agent_name}' at {a2a_endpoint} failed: {e}")
        await _notify_delegation_end(
            call_graph, agent_name, response=f"Error: {e}"
        )
        return json.dumps({
            "status": "error",
            "error": f"Failed to reach agent '{agent_name}': {e}",
        })


def build_delegate_tool(
    agent_def,
    *,
    agent_registry=None,
    local_base_url: str = "http://localhost:8000",
    remote_agents: list[dict] | None = None,
    call_graph=None,
    client_request_id: str | None = None,
    context_headers: dict[str, str] | None = None,
    current_depth: int = 0,
    app_config=None,
    mcp_server_url: str | None = None,
):
    """Build a native ``FunctionTool`` for delegating to other agents.

    Supports two modes:

    * **By name** — provide ``agent_name``.  If the calling agent declares
      ``sub_agents``, the name must be in that allowlist.  Resolved to a URL
      via the local ``AgentRegistry`` or ``remote_agents`` config.
    * **By URL** — provide ``agent_url``.  Used for ad-hoc communication
      with agents discovered at runtime (e.g. via ``discover_agents``).

    Both modes share the same streaming, call-graph, and depth-limit logic.

    Args:
        agent_def: The calling agent's ``AgentDefinition``.
        agent_registry: ``AgentRegistry`` for resolving local agent names.
        local_base_url: Base URL of the local A2A server.
        remote_agents: List of ``{"url": "...", "name": "..."}`` for remote agents.
        client_request_id: Original client JSON-RPC id for session tracking.
        context_headers: Client-provided context headers to cascade to sub-agents.
        current_depth: Current delegation depth (for depth limit enforcement).

    Returns:
        A ``FunctionTool`` instance that can be passed to ``Agent(tools=[...])``.
    """
    from agents import FunctionTool

    allowed = list(agent_def.sub_agents) if agent_def.sub_agents else []

    async def _on_invoke(ctx, args_json: str) -> str:
        """Invoked by the Agents SDK when the LLM calls the delegate tool."""
        args = json.loads(args_json)
        return await _delegate_impl(
            message=args["message"],
            agent_name=args.get("agent_name"),
            agent_url=args.get("agent_url"),
            allowed_sub_agents=allowed or None,
            from_agent_name=agent_def.name,
            agent_registry=agent_registry,
            local_base_url=local_base_url,
            remote_agents=remote_agents,
            current_depth=current_depth,
            call_graph=call_graph,
            client_request_id=client_request_id,
            context_headers=context_headers,
            app_config=app_config,
            mcp_server_url=mcp_server_url,
        )

    # Build a description that reflects available modes
    if allowed:
        desc = (
            "Delegate a task to another agent. "
            f"Known sub-agents (by name): {allowed}. "
            "You can also delegate to any agent by URL (e.g. from discover_agents). "
            "Provide either agent_name or agent_url, plus a message."
        )
    else:
        desc = (
            "Send a task to another agent. "
            "Use discover_agents to find available agents, then provide "
            "agent_name (for local/configured agents) or agent_url (for "
            "any agent). Returns the agent's response as JSON."
        )

    return FunctionTool(
        name="delegate",
        description=desc,
        params_json_schema={
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": (
                        "Name of the agent to delegate to. "
                        + (f"Known sub-agents: {allowed}. " if allowed else "")
                        + "Use this for local or configured agents."
                    ),
                },
                "agent_url": {
                    "type": "string",
                    "description": (
                        "Full A2A URL of the agent (e.g. http://host:port/agents/name). "
                        "Use this for agents discovered at runtime."
                    ),
                },
                "message": {
                    "type": "string",
                    "description": "The task or message to send to the agent.",
                },
            },
            "required": ["message"],
            "additionalProperties": False,
        },
        on_invoke_tool=_on_invoke,
        strict_json_schema=False,
    )
