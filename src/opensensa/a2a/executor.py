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

"""FrameworkAgentExecutor — bridges A2A protocol requests to OpenAI Agents SDK execution.

Implements the a2a-sdk AgentExecutor interface. Each executor instance is
bound to exactly one agent (1 agent = 1 URL = 1 executor). When an A2A
SendMessage arrives on that agent's sub-app, this executor:
  1. Extracts the user message from the RequestContext
  2. Builds an OpenAI Agents SDK Agent with MCP tools
  3. Runs the agent via Runner.run() (non-streaming) or Runner.run_streamed()
  4. Publishes results into the EventQueue as A2A events

For ``message/send`` the executor uses ``Runner.run()`` and returns the
final result.  For ``message/stream`` it uses ``Runner.run_streamed()``
and publishes incremental ``TaskStatus`` / ``TaskArtifactUpdate`` events
via SSE as the LLM generates tokens.
"""

import asyncio
import json as _json
import logging
import uuid as _uuid
from contextlib import AsyncExitStack
from typing import Any, Optional

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import (
    DataPart,
    TaskState,
    TextPart,
)

from opensensa.config import AppConfig
from opensensa.orchestrator.agent_registry import AgentRegistry
from opensensa.orchestrator.tracing import AgentTraceContext

logger = logging.getLogger("opensensa.a2a")

# Header used to propagate current delegation depth across agent hops
_DEPTH_HEADER = "X-A2A-Depth"

# Header used to propagate the original client JSON-RPC id across all hops
_CLIENT_ID_HEADER = "X-A2A-Client-Request-Id"


def _build_event_metadata(event: dict) -> dict[str, Any]:
    """Build ``framework:*`` metadata dict from an internal ``__event__`` dict.

    Maps ``{"__event__": "tool_start", "tool": "search"}`` →
    ``{"framework:event": "tool_start", "framework:tool": "search"}``.

    This metadata is attached to A2A ``Message.metadata`` on status-update
    messages, giving clients a structured way to parse rich events without
    having to JSON-parse the text field.
    """
    return {
        f"framework:{k.strip('_')}": v
        for k, v in event.items()
        if v is not None
    }


# ---------------------------------------------------------------------------
# A2ACallGraphAdapter — emits delegation events into the A2A SSE stream
# ---------------------------------------------------------------------------

class A2ACallGraphAdapter:
    """Lightweight call-graph adapter for use inside A2A executors.

    Implements the same synchronous interface as ``WebCallGraph``
    (``start_delegation``, ``end_delegation``, ``update_delegation_target``,
    ``add_delegation_sub_event``) but instead of pushing events to a browser
    SSE queue, it publishes ``__event__`` JSON payloads as A2A
    ``status-update`` messages via the ``TaskUpdater``.

    This enables **nested delegation visibility**: when Agent B (invoked
    from A) delegates to Agent C, the ``delegation_start`` /
    ``delegation_end`` events appear in B's SSE stream.  Agent A's
    ``_try_stream_delegation()`` parses them and forwards to A's own
    ``call_graph`` — which may be a ``WebCallGraph`` pushing to the
    browser, creating a recursive forwarding chain.

    The adapter exposes **async** ``emit_*`` methods that callers should
    ``await`` when possible (guaranteeing delivery).  The sync
    ``start_delegation`` / ``end_delegation`` methods are kept as
    fire-and-forget fallbacks for call-sites that cannot ``await``.
    """

    def __init__(self, updater: "TaskUpdater", agent_name: str) -> None:
        self._updater = updater
        self._agent_name = agent_name

    # -- Core async emit (guaranteed delivery) --------------------------------

    async def _emit_async(self, event: dict) -> None:
        """Emit a structured JSON event as an A2A status-update message.

        Event data is delivered via ``message.metadata`` using ``framework:*``
        keys.  The text part is left empty — clients should read metadata,
        not parse parts text.
        """
        etype = event.get("__event__", "unknown")
        logger.info(f"A2ACallGraphAdapter[{self._agent_name}]: emitting {etype}")
        try:
            metadata = _build_event_metadata(event)
            msg = self._updater.new_agent_message(
                parts=[TextPart(kind="text", text="")],
                metadata=metadata,
            )

            await self._updater.update_status(
                state=TaskState.working,
                message=msg,
            )
            logger.info(f"A2ACallGraphAdapter[{self._agent_name}]: emitted {etype} OK")
        except Exception as exc:
            logger.warning(f"A2ACallGraphAdapter[{self._agent_name}]: failed to emit {etype}: {exc}")

    # -- Async methods (preferred — callers should await these) ---------------

    async def emit_delegation_start(
        self, from_agent: str, to_agent: str, *, message: str = ""
    ) -> None:
        """Await-able emit of ``delegation_start`` into the A2A SSE stream."""
        await self._emit_async({
            "__event__": "delegation_start",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "message": message,
        })

    async def emit_delegation_end(
        self, to_agent: str, *, response: str = ""
    ) -> None:
        """Await-able emit of ``delegation_end`` into the A2A SSE stream."""
        await self._emit_async({
            "__event__": "delegation_end",
            "to_agent": to_agent,
            "response": response,
        })

    # -- Sync fallbacks (fire-and-forget, used when caller cannot await) ------

    def _fire_and_forget(self, event: dict) -> None:
        """Schedule an async emit — best-effort, no delivery guarantee."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._emit_async(event))
        except RuntimeError:
            logger.debug("No running event loop — cannot emit delegation event")

    def start_delegation(
        self, from_agent: str, to_agent: str, *, message: str = ""
    ) -> None:
        """Sync fallback — prefer ``emit_delegation_start`` when possible."""
        self._fire_and_forget({
            "__event__": "delegation_start",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "message": message,
        })

    def end_delegation(
        self, to_agent: str, *, response: str = "", duration_ms: int = 0
    ) -> None:
        """Sync fallback — prefer ``emit_delegation_end`` when possible."""
        self._fire_and_forget({
            "__event__": "delegation_end",
            "to_agent": to_agent,
            "response": response,
        })

    def update_delegation_target(self, agent_name: str) -> None:
        """No-op — target is implicit in ``delegation_start``."""

    def add_delegation_sub_event(
        self, event_type: str, tool_name: str, **kwargs
    ) -> None:
        """No-op for sub-events already handled by the executor's streaming loop."""


class FrameworkAgentExecutor(AgentExecutor):
    """Executes agent requests by bridging A2A → OpenAI Agents SDK.

    Each instance is bound to a specific agent via ``agent_name``.
    There is no runtime routing — the agent identity is determined
    by which A2A sub-app received the request.

    Supports both synchronous (``message/send``) and streaming
    (``message/stream``) execution modes.
    """

    def __init__(
        self,
        agent_name: str,
        agent_registry: AgentRegistry,
        config: AppConfig,
        mcp_server_url: str = "http://localhost:8001/mcp",
        timeout: float = 300.0,
    ):
        self._agent_name = agent_name
        self._registry = agent_registry
        self._config = config
        self._mcp_server_url = mcp_server_url
        self._timeout = timeout  # seconds; 0 or None = no timeout
        # Track running tasks for cancellation
        self._running_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _build_agent_context(
        self,
        context: RequestContext,
        exit_stack: AsyncExitStack,
        *,
        call_graph=None,
    ):
        """Build the OpenAI Agents SDK Agent and extract metadata.

        Args:
            call_graph: Optional call-graph adapter (e.g. ``A2ACallGraphAdapter``)
                passed through to ``build_agent()`` so the delegate tool can
                emit delegation events into the SSE stream.

        Returns ``(agent, user_input, depth)`` or raises on validation errors.
        """
        agent_name = self._agent_name
        agent_def = self._registry.get(agent_name)
        if not agent_def:
            available = self._registry.agent_names()
            raise ValueError(f"Agent '{agent_name}' not found. Available: {available}")

        user_input_text = context.get_user_input()
        if not user_input_text:
            raise ValueError("No message content provided.")

        req_meta = context.metadata or {}

        # --- Multi-turn conversation history (framework:history) ---
        # Clients can pass prior conversation turns via framework:history
        # in either params.metadata or params.message.metadata.  When
        # present we build a list[EasyInputMessageParam] that the OpenAI
        # Agents SDK Runner accepts as ``input``.
        user_input: str | list[dict] = user_input_text
        history = req_meta.get("framework:history")
        if not history and context.message and context.message.metadata:
            history = context.message.metadata.get("framework:history")
        if history and isinstance(history, list):
            input_messages: list[dict] = []
            for turn in history:
                role = turn.get("role", "user")
                # Normalize A2A role "agent" → OpenAI "assistant"
                if role == "agent":
                    role = "assistant"
                # Extract text from parts list or fall back to direct content
                parts = turn.get("parts")
                if isinstance(parts, list):
                    text = "\n".join(
                        p.get("text", "") for p in parts if isinstance(p, dict)
                    )
                else:
                    text = turn.get("content", "")
                if text:
                    input_messages.append({"role": role, "content": text})
            # Append the current user message as the final turn
            input_messages.append({"role": "user", "content": user_input_text})
            user_input = input_messages
            logger.debug(
                "Multi-turn input: %d history turns + current message",
                len(input_messages) - 1,
            )

        # Read delegation depth from HTTP headers (via ServerCallContext.state)
        # or from JSON-RPC metadata as fallback
        depth = 0
        call_ctx = context.call_context
        if call_ctx and call_ctx.state.get(_DEPTH_HEADER.lower()):
            try:
                depth = int(call_ctx.state[_DEPTH_HEADER.lower()])
            except (TypeError, ValueError):
                pass
        elif _DEPTH_HEADER in req_meta:
            try:
                depth = int(req_meta[_DEPTH_HEADER])
            except (TypeError, ValueError):
                pass

        # Read client request id from HTTP headers (via ServerCallContext.state)
        # This is the original JSON-RPC id from the client, propagated through
        # all delegation hops so sub-agents and tools share the same session id.
        client_request_id: str | None = None
        if call_ctx and call_ctx.state.get(_CLIENT_ID_HEADER.lower()):
            client_request_id = call_ctx.state[_CLIENT_ID_HEADER.lower()]

        from opensensa.orchestrator.agent_builder import build_agent

        # Infrastructure headers required by the MCP tool server.
        # X-Conversation-Id is mandatory for tool logging; without it
        # tool calls raise RuntimeError and the LLM reports a "technical issue".
        mcp_headers: dict[str, str] = {
            "X-Conversation-Id": context.task_id or "a2a-unknown",
            "X-Agent-Id": agent_name,
            "X-Agent-Depth": str(depth),
        }
        # Merge per-request context headers from client metadata.
        request_headers = req_meta.get("context_headers", {})
        if isinstance(request_headers, dict):
            mcp_headers.update(request_headers)

        remote_agents = [
            {"url": ra.url, "name": getattr(ra, "name", "")}
            for ra in self._config.remote_agents
        ]

        agent = await build_agent(
            agent_def=agent_def,
            config=self._config,
            mcp_server_url=self._mcp_server_url,
            exit_stack=exit_stack,
            mcp_headers=mcp_headers if mcp_headers else None,
            agent_registry=self._registry,
            remote_agents=remote_agents or None,
            call_graph=call_graph,
            client_request_id=client_request_id,
            context_headers=mcp_headers if mcp_headers else None,
            current_depth=depth,
        )

        return agent, user_input, depth

    # ------------------------------------------------------------------
    # Non-streaming execution  (message/send)
    # ------------------------------------------------------------------

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Execute an agent request.

        Uses ``Runner.run_streamed()`` so that intermediate events (tool
        calls, text deltas) are published to the EventQueue in real-time.
        The A2A SDK's ``DefaultRequestHandler`` always calls this method
        for both ``message/send`` and ``message/stream`` — the difference
        is only in how events are delivered to the client.
        """
        task_id = context.task_id or "unknown"
        context_id = context.context_id or "unknown"

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task_id,
            context_id=context_id,
        )

        trace = AgentTraceContext()
        span = trace.start_span(self._agent_name, event_type="a2a_execute")

        try:
            await updater.start_work()

            async with AsyncExitStack() as exit_stack:
                call_graph_adapter = A2ACallGraphAdapter(updater, self._agent_name)

                agent, user_input, _depth = await self._build_agent_context(
                    context, exit_stack, call_graph=call_graph_adapter
                )

                logger.info(f"Executing agent '{self._agent_name}' for task {task_id}")

                from agents import Runner
                from agents.stream_events import RunItemStreamEvent, RawResponsesStreamEvent

                streamed_result = Runner.run_streamed(
                    starting_agent=agent,
                    input=user_input,
                    max_turns=25,
                )

                self._running_tasks[task_id] = asyncio.current_task()

                accumulated_text = ""
                chunk_count = 0
                _tracked_tools: list[dict] = []
                _pending_calls: dict[str, str] = {}  # call_id → tool_name
                _response_artifact_id = str(_uuid.uuid4())
                _first_artifact_chunk = True

                try:
                    async for event in streamed_result.stream_events():
                        event_type = type(event).__name__
                        logger.debug(f"[stream] event type={event_type}")

                        # -- Token-level text deltas --
                        if isinstance(event, RawResponsesStreamEvent):
                            raw_evt = event.data
                            raw_type = getattr(raw_evt, "type", "unknown")
                            if raw_type == "response.output_text.delta":
                                delta = getattr(raw_evt, "delta", "")
                                if delta:
                                    accumulated_text += delta
                                    chunk_count += 1

                                    await updater.update_status(
                                        state=TaskState.working,
                                        message=updater.new_agent_message(
                                            parts=[TextPart(kind="text", text=delta)]
                                        ),
                                    )

                                    await updater.add_artifact(
                                        parts=[TextPart(kind="text", text=delta)],
                                        artifact_id=_response_artifact_id,
                                        name=f"{self._agent_name}-response",
                                        append=not _first_artifact_chunk,
                                        last_chunk=False,
                                    )
                                    _first_artifact_chunk = False
                            continue

                        if isinstance(event, RunItemStreamEvent):
                            item = event.item
                            raw = getattr(item, "raw_item", None)
                            item_type = getattr(item, "type", "")

                            # -- Tool call started --
                            if item_type == "tool_call_item":
                                tool_name = getattr(raw, "name", None) or "unknown"
                                # McpCall uses 'id' instead of 'call_id'
                                call_id = getattr(raw, "call_id", None) or getattr(raw, "id", None) or ""
                                if call_id:
                                    _pending_calls[call_id] = tool_name

                                entry: dict = {"name": tool_name, "_cid": call_id}
                                evt: dict = {"__event__": "tool_start", "tool": tool_name}

                                if tool_name == "delegate":
                                    args_str = getattr(raw, "arguments", "")
                                    if args_str:
                                        try:
                                            a_data = _json.loads(args_str)
                                            aname = a_data.get("agent_name", "")
                                            if aname:
                                                entry["agent"] = aname
                                                evt["agent"] = aname
                                        except (ValueError, TypeError):
                                            pass

                                _tracked_tools.append(entry)
                                await updater.update_status(
                                    state=TaskState.working,
                                    message=updater.new_agent_message(
                                        parts=[TextPart(kind="text", text="")],
                                        metadata=_build_event_metadata(evt),
                                    ),
                                )
                                continue

                            # -- Tool call finished --
                            if item_type == "tool_call_output_item":
                                # raw_item is a TypedDict (FunctionCallOutput) or similar — extract call id
                                # McpCall uses 'id' instead of 'call_id', mirror SDK's _extract_call_id
                                if isinstance(raw, dict):
                                    call_id = raw.get("call_id") or raw.get("id") or ""
                                else:
                                    call_id = getattr(raw, "call_id", None) or getattr(raw, "id", None) or ""
                                tool_name = _pending_calls.pop(call_id, "unknown")
                                if isinstance(raw, dict):
                                    output = str(raw.get("output", "") or getattr(item, "output", "") or "")
                                else:
                                    output = str(getattr(raw, "output", "") or getattr(item, "output", "") or "")

                                evt_data: dict = {"__event__": "tool_end", "tool": tool_name}

                                if tool_name == "delegate" and output:
                                    try:
                                        d_data = _json.loads(output)
                                        if d_data.get("agent"):
                                            evt_data["agent"] = d_data["agent"]
                                        if d_data.get("tools_used"):
                                            evt_data["tools_used"] = d_data["tools_used"]
                                        for t in _tracked_tools:
                                            if t.get("_cid") == call_id:
                                                if d_data.get("agent"):
                                                    t["agent"] = d_data["agent"]
                                                if d_data.get("tools_used"):
                                                    t["tools_used"] = d_data["tools_used"]
                                                break
                                    except (ValueError, TypeError):
                                        pass

                                await updater.update_status(
                                    state=TaskState.working,
                                    message=updater.new_agent_message(
                                        parts=[TextPart(kind="text", text="")],
                                        metadata=_build_event_metadata(evt_data),
                                    ),
                                )
                                continue

                            # -- Text content (fallback if no raw deltas) --
                            if raw is not None and chunk_count == 0:
                                content_parts = getattr(raw, "content", [])
                                for part in content_parts:
                                    text = getattr(part, "text", None)
                                    if text:
                                        chunk_text = text[len(accumulated_text):] if text.startswith(accumulated_text) else text
                                        if chunk_text:
                                            accumulated_text = text
                                            chunk_count += 1

                                            await updater.update_status(
                                                state=TaskState.working,
                                                message=updater.new_agent_message(
                                                    parts=[TextPart(kind="text", text=chunk_text)]
                                                ),
                                            )

                                            await updater.add_artifact(
                                                parts=[TextPart(kind="text", text=chunk_text)],
                                                artifact_id=_response_artifact_id,
                                                name=f"{self._agent_name}-response",
                                                append=not _first_artifact_chunk,
                                                last_chunk=False,
                                            )
                                            _first_artifact_chunk = False

                finally:
                    self._running_tasks.pop(task_id, None)

                # Extract final text
                final_text = ""
                if streamed_result.is_complete:
                    fo = getattr(streamed_result, "final_output", None)
                    if fo:
                        final_text = str(fo) if not isinstance(fo, str) else fo

                if not final_text:
                    final_text = accumulated_text or "Agent completed with no output."

                # Publish execution-trace artifact with tool call info
                for t in _tracked_tools:
                    t.pop("_cid", None)
                if _tracked_tools:
                    await updater.add_artifact(
                        parts=[DataPart(
                            kind="data",
                            data={"tools_used": _tracked_tools},
                        )],
                        name=f"{self._agent_name}-execution-trace",
                    )

                # Close the response artifact
                await updater.add_artifact(
                    parts=[TextPart(kind="text", text="")],
                    artifact_id=_response_artifact_id,
                    name=f"{self._agent_name}-response",
                    append=not _first_artifact_chunk,
                    last_chunk=True,
                )

                self._record_usage(span, streamed_result)

                await updater.complete(
                    message=updater.new_agent_message(
                        parts=[TextPart(kind="text", text=final_text)]
                    )
                )

                span.complete(
                    "completed",
                    output_length=len(final_text),
                    chunks=chunk_count,
                )
                logger.info(
                    f"Agent '{self._agent_name}' completed task {task_id} "
                    f"({chunk_count} chunks, output length={len(final_text)})"
                )

        except ValueError as ve:
            span.complete("error", error=str(ve))
            await updater.failed(
                message=updater.new_agent_message(
                    parts=[TextPart(kind="text", text=str(ve))]
                )
            )
        except asyncio.CancelledError:
            span.complete("cancelled")
            logger.info(f"Agent execution cancelled for task {task_id}")
            await updater.cancel(
                message=updater.new_agent_message(
                    parts=[TextPart(kind="text", text="Task was cancelled.")]
                )
            )
        except asyncio.TimeoutError:
            span.complete("timeout")
            logger.warning(f"Agent execution timed out for task {task_id} ({self._timeout}s)")
            self._running_tasks.pop(task_id, None)
            await updater.failed(
                message=updater.new_agent_message(
                    parts=[TextPart(kind="text", text=f"Agent execution timed out after {self._timeout}s.")]
                )
            )
        except Exception as e:
            span.complete("error", error=str(e))
            logger.error(f"Agent execution failed for task {task_id}: {e}", exc_info=True)
            await updater.failed(
                message=updater.new_agent_message(
                    parts=[TextPart(kind="text", text=f"Agent execution error: {e}")]
                )
            )

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Cancel a running agent execution."""
        task_id = context.task_id or "unknown"
        context_id = context.context_id or "unknown"

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task_id,
            context_id=context_id,
        )

        running = self._running_tasks.get(task_id)
        if running and not running.done():
            running.cancel()
            logger.info(f"Cancelled running task: {task_id}")

        await updater.cancel(
            message=updater.new_agent_message(
                parts=[TextPart(kind="text", text="Task cancelled by request.")]
            )
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------


    @staticmethod
    def _record_usage(span, result) -> None:
        """Record token usage from the result into a trace span."""
        raw_responses = getattr(result, "raw_responses", None)
        if not raw_responses:
            return
        total_in = total_out = 0
        for resp in raw_responses:
            u = getattr(resp, "usage", None)
            if u:
                total_in += getattr(u, "input_tokens", 0)
                total_out += getattr(u, "output_tokens", 0)
        if total_in or total_out:
            span.usage = {
                "input_tokens": total_in,
                "output_tokens": total_out,
                "total_tokens": total_in + total_out,
            }
