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


async def _delegate_impl(
    agent_name: str,
    message: str,
    *,
    allowed_sub_agents: list[str],
    from_agent_name: str = "unknown",
    agent_registry=None,
    local_base_url: str = "http://localhost:8000",
    remote_agents: list[dict] | None = None,
    current_depth: int = 0,
    call_graph=None,
    client_request_id: str | None = None,
    context_headers: dict[str, str] | None = None,
) -> str:
    """Core delegation logic — sends an A2A ``message/send`` to a sub-agent.

    Returns a JSON string (the Agents SDK expects function tools to return str).
    """
    # Validate that the target agent is in the caller's sub_agents list
    if agent_name not in allowed_sub_agents:
        return json.dumps({
            "status": "error",
            "error": (
                f"Agent '{agent_name}' is not in your sub_agents list. "
                f"Allowed sub-agents: {allowed_sub_agents}"
            ),
        })

    # Enforce depth limit
    if current_depth >= MAX_DELEGATION_DEPTH:
        logger.warning(
            f"Delegation depth limit reached ({current_depth}/{MAX_DELEGATION_DEPTH}). "
            f"Refusing to delegate to '{agent_name}'."
        )
        return json.dumps({
            "status": "error",
            "error": (
                f"Delegation depth limit reached ({MAX_DELEGATION_DEPTH}). "
                "This prevents infinite agent-to-agent loops. "
                "Try handling this task directly instead of delegating."
            ),
        })

    # Resolve agent name → URL
    agent_url = _resolve_agent_url(
        agent_name,
        agent_registry=agent_registry,
        local_base_url=local_base_url,
        remote_agents=remote_agents,
    )
    if not agent_url:
        return json.dumps({
            "status": "error",
            "error": (
                f"Agent '{agent_name}' not found. "
                f"Make sure it exists as a local or remote agent."
            ),
        })

    # Build A2A request parameters
    a2a_endpoint = f"{agent_url.rstrip('/')}/"

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

    # ---- Try streaming first for real-time sub-agent visibility ----
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
    except Exception as exc:
        logger.warning(
            f"Streaming delegation to '{agent_name}' failed ({type(exc).__name__}: {exc}), "
            "falling back to sync message/send"
        )

    # ---- Sync fallback (message/send) ----
    payload = {
        "jsonrpc": "2.0",
        "id": client_request_id or str(uuid.uuid4()),
        "method": "message/send",
        "params": params,
    }

    try:
        async with httpx.AsyncClient(timeout=_A2A_TIMEOUT) as client:
            resp = await client.post(a2a_endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()

            if "error" in result:
                return json.dumps({"status": "error", "error": result["error"]})

            # Extract tool call trace from execution-trace artifact if present
            tools_used: list[dict] = []
            task_result = result.get("result", {})
            for artifact in task_result.get("artifacts", []):
                aname = artifact.get("name", "")
                if aname.endswith("-execution-trace"):
                    for part in artifact.get("parts", []):
                        if part.get("kind") == "data":
                            data = part.get("data", {})
                            tools_used = data.get("tools_used", [])

            response: dict[str, Any] = {
                "status": "success",
                "agent": agent_name,
                "result": task_result,
            }
            if tools_used:
                response["tools_used"] = tools_used

            delegate_response = _extract_response_text(task_result)
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
):
    """Build a native ``FunctionTool`` for delegating to sub-agents.

    Args:
        agent_def: The calling agent's ``AgentDefinition`` (used to read ``sub_agents``).
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

    allowed = list(agent_def.sub_agents)

    async def _on_invoke(ctx, args_json: str) -> str:
        """Invoked by the Agents SDK when the LLM calls the delegate tool."""
        args = json.loads(args_json)
        return await _delegate_impl(
            agent_name=args["agent_name"],
            message=args["message"],
            allowed_sub_agents=allowed,
            from_agent_name=agent_def.name,
            agent_registry=agent_registry,
            local_base_url=local_base_url,
            remote_agents=remote_agents,
            current_depth=current_depth,
            call_graph=call_graph,
            client_request_id=client_request_id,
            context_headers=context_headers,
        )

    return FunctionTool(
        name="delegate",
        description=(
            "Delegate a task to a sub-agent by name. "
            f"Available sub-agents: {allowed}. "
            "Returns the agent's response as JSON."
        ),
        params_json_schema={
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": f"Name of the sub-agent to delegate to. Must be one of: {allowed}",
                },
                "message": {
                    "type": "string",
                    "description": "The task or message to send to the sub-agent.",
                },
            },
            "required": ["agent_name", "message"],
            "additionalProperties": False,
        },
        on_invoke_tool=_on_invoke,
        strict_json_schema=True,
    )
