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

"""Interactive chat session — run agents conversationally in the terminal.

This module provides the ``ChatSession`` class that powers ``opensensa chat``.
It starts the MCP tool server in the background, builds agents via the
OpenAI Agents SDK, and displays responses with Rich formatting.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import socket
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

# Disable the OpenAI Agents SDK built-in tracing — it sends telemetry to
# OpenAI's API which fails with non-OpenAI models (e.g. "unknown parameter:
# total_tokens").  OpenSensa has its own tracing skeleton in orchestrator/tracing.py.
try:
    from agents.tracing import set_tracing_disabled  # type: ignore[import-untyped]
    set_tracing_disabled(True)
except ImportError:
    pass

logger = logging.getLogger(__name__)

from opensensa.config import AppConfig
from opensensa.orchestrator.agent_registry import AgentDefinition, AgentRegistry
from opensensa.interactive.call_graph import CallGraph
from opensensa.interactive.ui import (
    console,
    get_spinner,
    print_agent_response,
    print_agent_selector,
    print_agents_list,
    print_error,
    print_help,
    print_info,
    print_tool_call,
    print_tool_result,
    print_tools_list,
    print_welcome,
)


# ---------------------------------------------------------------------------
# RunHooks → real-time tool-call display
# ---------------------------------------------------------------------------

def _make_hooks(call_graph: CallGraph | None = None):
    """Create RunHooks that update the live call-graph AND emit structured logs.

    When *call_graph* is provided, tool calls, LLM invocations, delegations
    and agent lifecycle events are pushed into it so ``Live`` can render
    a real-time tree.  Structured JSON logs are always emitted regardless.

    Returns ``None`` if the agents SDK doesn't expose RunHooks.
    """
    try:
        from agents import RunHooks  # type: ignore[attr-defined]

        _hook_logger = logging.getLogger("opensensa.hooks")

        class _ChatHooks(RunHooks):
            def __init__(self, graph: CallGraph | None = None):
                self._graph = graph
                self._llm_start_time: float = 0.0
                self._tool_start_times: dict[str, float] = {}
                self._agent_start_time: float = 0.0

            # -- LLM calls ---------------------------------------------------

            async def on_llm_start(self, context, agent, system_prompt, input_items):
                self._llm_start_time = time.monotonic()
                agent_name = getattr(agent, "name", str(agent))
                if self._graph:
                    self._graph.start_llm(agent_name)
                _structured_log(_hook_logger, "llm_start", {
                    "agent": agent_name,
                    "input_items_count": len(input_items) if input_items else 0,
                })

            async def on_llm_end(self, context, agent, response):
                duration_ms = int((time.monotonic() - self._llm_start_time) * 1000)
                usage = getattr(response, "usage", None)
                usage_data = {}
                total_tokens = 0
                if usage:
                    usage_data = {
                        "input_tokens": getattr(usage, "input_tokens", 0),
                        "output_tokens": getattr(usage, "output_tokens", 0),
                        "total_tokens": getattr(usage, "total_tokens", 0),
                        "requests": getattr(usage, "requests", 0),
                    }
                    total_tokens = usage_data["total_tokens"]
                    cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0)
                    reasoning = getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0)
                    if cached:
                        usage_data["cached_tokens"] = cached
                    if reasoning:
                        usage_data["reasoning_tokens"] = reasoning

                agent_name = getattr(agent, "name", str(agent))
                if self._graph:
                    self._graph.end_llm(
                        agent_name=agent_name,
                        duration_ms=duration_ms,
                        tokens=total_tokens,
                    )

                _structured_log(_hook_logger, "llm_end", {
                    "agent": agent_name,
                    "duration_ms": duration_ms,
                    "usage": usage_data,
                    "response_id": getattr(response, "response_id", None),
                })

            # -- Tools -------------------------------------------------------

            async def on_tool_start(self, context, agent, tool):
                name = getattr(tool, "name", None) or str(tool)
                self._tool_start_times[name] = time.monotonic()
                if self._graph:
                    self._graph.start_tool(name)
                else:
                    print_tool_call(name)
                _structured_log(_hook_logger, "tool_start", {
                    "agent": getattr(agent, "name", str(agent)),
                    "tool": name,
                })

            async def on_tool_end(self, context, agent, tool, result):
                name = getattr(tool, "name", None) or str(tool)
                duration_ms = int((time.monotonic() - self._tool_start_times.pop(name, time.monotonic())) * 1000)
                text = str(result) if result else ""
                if self._graph:
                    # Pass full text — call_graph needs complete JSON for
                    # delegate results; it handles truncation internally.
                    self._graph.end_tool(name, duration_ms=duration_ms, result=text)
                else:
                    if len(text) > 200:
                        text = text[:200] + "…"
                    print_tool_result(name, text)
                _structured_log(_hook_logger, "tool_end", {
                    "agent": getattr(agent, "name", str(agent)),
                    "tool": name,
                    "duration_ms": duration_ms,
                    "result_length": len(str(result)) if result else 0,
                })

            # -- Agent lifecycle ---------------------------------------------

            async def on_agent_start(self, context, agent):
                self._agent_start_time = time.monotonic()
                agent_name = getattr(agent, "name", str(agent))
                if self._graph:
                    self._graph.start_agent(agent_name)
                _structured_log(_hook_logger, "agent_start", {
                    "agent": agent_name,
                })

            async def on_agent_end(self, context, agent, output):
                duration_ms = int((time.monotonic() - self._agent_start_time) * 1000)
                agent_name = getattr(agent, "name", str(agent))
                if self._graph:
                    self._graph.end_agent(agent_name, duration_ms=duration_ms)
                _structured_log(_hook_logger, "agent_end", {
                    "agent": agent_name,
                    "duration_ms": duration_ms,
                    "output_length": len(str(output)) if output else 0,
                })

            # -- Handoffs (delegation) ---------------------------------------

            async def on_handoff(self, context, from_agent, to_agent):
                from_name = getattr(from_agent, "name", str(from_agent))
                to_name = getattr(to_agent, "name", str(to_agent))
                if self._graph:
                    self._graph.start_delegation(from_name, to_name)
                _structured_log(_hook_logger, "handoff", {
                    "from_agent": from_name,
                    "to_agent": to_name,
                })

        return _ChatHooks(graph=call_graph)
    except ImportError:
        # RunHooks not available in this version of the agents SDK
        return None
    except Exception:
        logging.getLogger("opensensa.chat").warning(
            "Failed to create RunHooks — tool call display disabled",
            exc_info=True,
        )
        return None


def _structured_log(lgr: logging.Logger, event: str, data: dict) -> None:
    """Emit a structured log record with *data* merged into the JSON output."""
    record = lgr.makeRecord(
        name=lgr.name,
        level=logging.INFO,
        fn="",
        lno=0,
        msg=event,
        args=(),
        exc_info=None,
    )
    record.structured_data = {"event": event, **data}  # type: ignore[attr-defined]
    lgr.handle(record)


# ---------------------------------------------------------------------------
# MCP server background process
# ---------------------------------------------------------------------------

def _run_mcp_background(config: AppConfig) -> None:
    """Entry-point for the background MCP server subprocess."""
    import logging
    import os
    import sys

    # Silence all logging so it doesn't bleed into the chat UI
    logging.disable(logging.CRITICAL)

    # Redirect stdout/stderr to devnull
    devnull = open(os.devnull, "w")
    sys.stdout = devnull
    sys.stderr = devnull

    os.environ.setdefault("DANGEROUSLY_OMIT_AUTH", "true")

    from opensensa.mcp_server.server import create_mcp_server
    from opensensa.mcp_server.tool_loader import discover_and_load_tools

    mcp = create_mcp_server(
        host=config.server.host,
        port=config.server.mcp_port,
    )

    # Framework tools
    agents_dir = Path(config.agents.directory).resolve()
    registry = AgentRegistry(agents_dir)
    remote_agents = [{"url": ra.url} for ra in config.remote_agents]

    # Build local base URL for discover_agents
    advertise_host = "localhost" if config.server.host == "0.0.0.0" else config.server.host
    local_base_url = f"http://{advertise_host}:{config.server.orchestrator_port}"

    from opensensa.framework_tools import create_agent, edit_agent, delete_agent, discover_agents, list_tools, send_to_agent

    discover_agents.register(
        mcp,
        agent_registry=registry,
        remote_agents=remote_agents,
        local_base_url=local_base_url,
    )
    send_to_agent.register(mcp)
    # NOTE: delegate is NOT registered on MCP — it is a native FunctionTool
    # wired directly into the Agent by agent_builder.py (A2A, not MCP).
    create_agent.register(mcp, agents_directory=config.agents.directory)
    edit_agent.register(mcp, agents_directory=config.agents.directory)
    delete_agent.register(mcp, agents_directory=config.agents.directory)
    list_tools.register(mcp)

    # User tools
    tools_dir = Path(config.tools.directory).resolve()
    discover_and_load_tools(tools_dir, mcp)

    mcp.run(transport="streamable-http")


def _run_a2a_background(config: AppConfig) -> None:
    """Entry-point for the background A2A server subprocess."""
    import logging
    import os
    import sys

    # Silence all logging so it doesn't bleed into the chat UI
    logging.disable(logging.CRITICAL)

    # Redirect stdout/stderr to devnull
    devnull = open(os.devnull, "w")
    sys.stdout = devnull
    sys.stderr = devnull

    import uvicorn

    from opensensa.orchestrator.agent_registry import AgentRegistry as _Reg
    from opensensa.orchestrator.server import create_orchestrator_app

    agents_dir = Path(config.agents.directory).resolve()
    registry = _Reg(agents_dir)
    registry.scan()

    mcp_server_url = f"http://localhost:{config.server.mcp_port}/mcp"
    app = create_orchestrator_app(config, registry, mcp_server_url=mcp_server_url)

    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.orchestrator_port,
        log_level="error",
    )


def _wait_for_port(port: int, host: str = "localhost", timeout: float = 20.0) -> None:
    """Block until *host:port* accepts a TCP connection."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except (ConnectionRefusedError, TimeoutError, OSError):
            time.sleep(0.3)
    raise TimeoutError(f"Server on port {port} not ready after {timeout}s")


# ---------------------------------------------------------------------------
# Friendly error classification
# ---------------------------------------------------------------------------

def _handle_chat_error(exc: BaseException) -> None:
    """Classify *exc* and display a user-friendly message via Rich.

    Instead of dumping the raw Python exception string, this looks for
    common categories (auth, rate-limit, model not found, connection, etc.)
    and shows a short actionable message.  The full exception is still
    logged at DEBUG level for developers.
    """
    logger.debug("Agent turn failed", exc_info=exc)

    msg = str(exc).strip()
    lower = msg.lower()

    # --- authentication / key ---
    if any(kw in lower for kw in ("401", "unauthorized", "api key", "authentication")):
        print_error(
            "Authentication failed — check your API key.\n"
            f"  [dim]{_truncate(msg)}[/dim]"
        )
        return

    # --- rate limit ---
    if any(kw in lower for kw in ("429", "rate limit", "rate_limit", "quota")):
        print_error(
            "Rate-limited by the provider — wait a moment and try again.\n"
            f"  [dim]{_truncate(msg)}[/dim]"
        )
        return

    # --- model not found ---
    if any(kw in lower for kw in ("model_not_found", "model not found", "does not exist")):
        print_error(
            "Model not found — check the model name in your agent or config.\n"
            f"  [dim]{_truncate(msg)}[/dim]"
        )
        return

    # --- connection errors ---
    if any(kw in lower for kw in ("connection", "timed out", "timeout", "unreachable", "dns")):
        print_error(
            "Connection error — unable to reach the LLM provider.\n"
            f"  [dim]{_truncate(msg)}[/dim]"
        )
        return

    # --- content filter / safety ---
    if any(kw in lower for kw in ("content_filter", "content filter", "content_policy", "safety")):
        print_error(
            "The request was blocked by the provider's content filter."
        )
        return

    # --- fallback: show a trimmed message ---
    print_error(_truncate(msg, max_len=300))


def _truncate(text: str, max_len: int = 200) -> str:
    """Shorten *text* to at most *max_len* characters."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


# ---------------------------------------------------------------------------
# Chat session
# ---------------------------------------------------------------------------

class ChatSession:
    """Manages the interactive conversation loop with a single agent."""

    def __init__(
        self,
        config: AppConfig,
        agent_def: AgentDefinition,
        registry: AgentRegistry,
    ):
        self.config = config
        self.agent_def = agent_def
        self.registry = registry
        self.mcp_server_url = f"http://localhost:{config.server.mcp_port}/mcp"
        self.conversation_history: list[Any] = []
        # Hooks and call_graph are created per-turn (see run_turn)
        self._hooks = None
        self._call_graph: CallGraph | None = None
        self._mcp_proc: Optional[multiprocessing.Process] = None
        self._a2a_proc: Optional[multiprocessing.Process] = None

    # -- MCP + A2A lifecycle -------------------------------------------------

    def _start_mcp(self) -> None:
        self._mcp_proc = multiprocessing.Process(
            target=_run_mcp_background,
            args=(self.config,),
            daemon=True,
        )
        self._mcp_proc.start()
        _wait_for_port(self.config.server.mcp_port)

    def _stop_mcp(self) -> None:
        if self._mcp_proc and self._mcp_proc.is_alive():
            self._mcp_proc.terminate()
            self._mcp_proc.join(timeout=3)

    def _start_a2a(self) -> None:
        """Start the A2A agent server in a background process."""
        self._a2a_proc = multiprocessing.Process(
            target=_run_a2a_background,
            args=(self.config,),
            daemon=True,
        )
        self._a2a_proc.start()
        _wait_for_port(self.config.server.orchestrator_port)

    def _stop_a2a(self) -> None:
        if self._a2a_proc and self._a2a_proc.is_alive():
            self._a2a_proc.terminate()
            self._a2a_proc.join(timeout=3)

    # -- Single turn ---------------------------------------------------------

    async def run_turn(self, user_input: str) -> str:
        """Send *user_input* to the agent and return its text response."""
        from agents import Runner
        from opensensa.orchestrator.tracing import AgentTraceContext

        turn_start = time.monotonic()
        _turn_logger = logging.getLogger("opensensa.chat")

        # Reuse the call graph if already set by the main loop (for Live display),
        # otherwise create a fresh one (e.g. if run_turn is called standalone).
        if self._call_graph is None:
            self._call_graph = CallGraph(agent_name=self.agent_def.name)
        self._hooks = _make_hooks(call_graph=self._call_graph)

        # Start a trace for this turn
        trace = AgentTraceContext()
        span = trace.start_span(self.agent_def.name, event_type="chat_turn")

        async with AsyncExitStack() as exit_stack:
            from opensensa.orchestrator.agent_builder import build_agent

            mcp_headers: dict[str, str] = {}
            if self.agent_def.context_headers:
                mcp_headers.update(self.agent_def.context_headers)

            # Build remote_agents list for delegate tool resolution
            remote_agents = [{"url": ra.url, "name": getattr(ra, 'name', '')} for ra in self.config.remote_agents]

            agent = await build_agent(
                agent_def=self.agent_def,
                config=self.config,
                mcp_server_url=self.mcp_server_url,
                exit_stack=exit_stack,
                mcp_headers=mcp_headers or None,
                agent_registry=self.registry,
                remote_agents=remote_agents or None,
                call_graph=self._call_graph,
            )

            # Build input — plain string for first turn, list for follow-ups
            if self.conversation_history:
                input_items = self.conversation_history.copy()
                input_items.append({"role": "user", "content": user_input})
                run_input: Any = input_items
            else:
                run_input = user_input

            result = await asyncio.wait_for(
                Runner.run(
                    starting_agent=agent,
                    input=run_input,
                    hooks=self._hooks,
                    max_turns=25,
                ),
                timeout=300.0,  # 5 minutes — matches executor timeout
            )

            # Persist history for multi-turn
            self.conversation_history = result.to_input_list()

            # --- Log turn summary ---
            turn_duration_ms = int((time.monotonic() - turn_start) * 1000)
            usage = getattr(result, "raw_responses", None)
            total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "requests": 0}
            if usage:
                for resp in usage:
                    u = getattr(resp, "usage", None)
                    if u:
                        total_usage["input_tokens"] += getattr(u, "input_tokens", 0)
                        total_usage["output_tokens"] += getattr(u, "output_tokens", 0)
                        total_usage["total_tokens"] += getattr(u, "total_tokens", 0)
                        total_usage["requests"] += getattr(u, "requests", 0)

            _structured_log(_turn_logger, "turn_complete", {
                "agent": self.agent_def.name,
                "duration_ms": turn_duration_ms,
                "history_length": len(self.conversation_history),
                "usage": total_usage,
            })

            # Record usage in trace span and complete it
            if total_usage["input_tokens"] or total_usage["output_tokens"]:
                span.usage = total_usage
            span.complete("completed", output_length=len(str(result.final_output or "")))

            # Extract text
            if result.final_output:
                return str(result.final_output)
            if result.new_items:
                parts = []
                for item in result.new_items:
                    for attr in ("text", "output"):
                        if hasattr(item, attr):
                            parts.append(str(getattr(item, attr)))
                            break
                return "\n".join(parts) if parts else "Agent completed with no output."
            return "Agent completed with no output."

    # -- Slash commands ------------------------------------------------------

    async def handle_command(self, raw: str) -> bool:
        """Process a ``/command``. Returns ``False`` when the user wants to quit."""
        parts = raw.strip().split(None, 1)
        cmd = parts[0].lower()

        if cmd in ("/quit", "/exit", "/q"):
            return False

        if cmd == "/help":
            print_help()
        elif cmd == "/clear":
            console.clear()
        elif cmd == "/agents":
            print_agents_list(self.registry.list_agents())
        elif cmd == "/tools":
            print_tools_list(self.agent_def.tools)
        elif cmd == "/model":
            model_display = self.agent_def.model
            try:
                from opensensa.config import resolve_model as _resolve_model
                resolved = _resolve_model(self.config, model_display)
                model_display = resolved.model_name
            except Exception:
                pass
            print_info(f"Model: [bold]{model_display}[/bold]")
        elif cmd == "/history":
            n = len(self.conversation_history)
            print_info(f"Conversation history: [bold]{n}[/bold] item(s)")
        elif cmd == "/reset":
            self.conversation_history = []
            print_info("[green]Conversation reset.[/green]")
        elif cmd == "/agent":
            if len(parts) < 2:
                print_error("Usage: /agent <name>")
                return True
            new_name = parts[1].strip()
            new_def = self.registry.get(new_name)
            if new_def:
                self.agent_def = new_def
                self.conversation_history = []
                console.print(
                    f"\n  [green]✓[/green] Switched to "
                    f"[bold cyan]{new_name}[/bold cyan] ({new_def.description})\n"
                )
            else:
                print_error(
                    f"Agent '{new_name}' not found. "
                    f"Available: {', '.join(self.registry.agent_names())}"
                )
        else:
            print_error(f"Unknown command: {cmd}  — type /help for commands.")
        return True

    # -- Main loop -----------------------------------------------------------

    async def start(self) -> None:
        """Show the welcome banner, start MCP, enter the chat loop."""

        # Resolve ${default} model token for display
        display_model = self.agent_def.model
        try:
            from opensensa.config import resolve_model as _resolve_model

            resolved = _resolve_model(self.config, display_model)
            display_model = resolved.model_name
        except Exception:
            pass

        print_welcome(
            agent_name=self.agent_def.name,
            description=self.agent_def.description,
            model=display_model,
            tools=self.agent_def.tools,
        )

        # Start the MCP tool server if the agent declares tools
        if self.agent_def.tools:
            try:
                console.print("  [dim]Starting tool server…[/dim]")
                self._start_mcp()
                console.print("  [green]✓[/green] [dim]Tool server ready[/dim]\n")
            except Exception as exc:
                print_error(f"Could not start tool server: {exc}")
                console.print("  [dim]Continuing without tools.[/dim]\n")

        # Start the A2A agent server so agents can call each other
        try:
            console.print("  [dim]Starting A2A agent server…[/dim]")
            self._start_a2a()
            agent_names = self.registry.agent_names()
            console.print(
                f"  [green]✓[/green] [dim]A2A server ready "
                f"({len(agent_names)} agent(s) at localhost:{self.config.server.orchestrator_port})[/dim]\n"
            )
        except Exception as exc:
            print_error(f"Could not start A2A server: {exc}")
            console.print("  [dim]Agent-to-agent calls will not work.[/dim]\n")

        # -- Input setup (prefer prompt_toolkit for history) -----------------
        prompt_session = None
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.formatted_text import HTML

            prompt_session = PromptSession(
                message=HTML("<ansigreen><b>&gt;</b></ansigreen> "),
            )
        except ImportError:
            pass

        loop = asyncio.get_running_loop()

        try:
            while True:
                # --- read user input ---
                try:
                    if prompt_session is not None:
                        user_input: str = await loop.run_in_executor(
                            None, prompt_session.prompt
                        )
                    else:
                        user_input = await loop.run_in_executor(
                            None, lambda: console.input("[bold green]>[/bold green] ")
                        )
                    user_input = user_input.strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if not user_input:
                    continue

                # --- slash commands ---
                if user_input.startswith("/"):
                    if not await self.handle_command(user_input):
                        break
                    continue

                # --- agent turn ---
                console.print()
                try:
                    from rich.live import Live

                    # Create a fresh call graph for this turn;
                    # run_turn() will attach it and create hooks.
                    call_graph = CallGraph(agent_name=self.agent_def.name)
                    self._call_graph = call_graph

                    with Live(
                        call_graph,
                        console=console,
                        refresh_per_second=8,
                        transient=True,  # clear the live display when done
                    ):
                        response = await self.run_turn(user_input)

                    # Print the final call graph summary if there were
                    # any tool calls or delegations (skip for pure LLM turns)
                    if not call_graph.is_empty:
                        console.print(call_graph.make_summary())

                    # Reset for next turn
                    self._call_graph = None

                    print_agent_response(response, self.agent_def.name)
                except KeyboardInterrupt:
                    console.print("\n  [dim]Interrupted.[/dim]\n")
                except Exception as exc:
                    _handle_chat_error(exc)
        finally:
            self._stop_mcp()
            self._stop_a2a()
            console.print("\n  [dim]Goodbye![/dim]\n")


# ---------------------------------------------------------------------------
# Top-level entry-point (called from CLI)
# ---------------------------------------------------------------------------

async def start_chat(
    config: AppConfig,
    registry: AgentRegistry,
    agent_name: str | None = None,
) -> None:
    """Launch the interactive chat with agent selection."""
    agents = registry.list_agents()

    if not agents:
        print_error(
            "No agents found. Run [bold]opensensa init[/bold] first to create a project."
        )
        return

    # --- pick an agent ---
    if agent_name:
        agent_def = registry.get(agent_name)
        if not agent_def:
            print_error(
                f"Agent '{agent_name}' not found. "
                f"Available: {', '.join(registry.agent_names())}"
            )
            return
    elif len(agents) == 1:
        agent_def = agents[0]
    else:
        # Interactive selector
        print_agent_selector(agents)
        try:
            choice = console.input("[bold green]>[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(agents):
                agent_def = agents[idx]
            else:
                print_error("Invalid selection.")
                return
        else:
            agent_def = registry.get(choice)
            if not agent_def:
                print_error(f"Agent '{choice}' not found.")
                return

    session = ChatSession(config=config, agent_def=agent_def, registry=registry)
    await session.start()
