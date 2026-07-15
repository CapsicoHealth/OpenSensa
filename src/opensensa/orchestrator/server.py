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

"""A2A + MCP orchestrator server.

Serves per-agent A2A endpoints — each agent gets its own
``A2AFastAPIApplication`` sub-app mounted at ``/agents/{name}/``.

Per the A2A spec, **one agent = one URL = one Agent Card**.

Layout:
  GET  /agents/{name}/.well-known/agent-card.json  — Agent Card
  POST /agents/{name}/                              — JSON-RPC endpoint
  GET  /health                                      — operational
  GET  /agents                                      — list all agents
"""

import logging
from typing import Any

from fastapi import FastAPI
from starlette.requests import Request

from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.apps.jsonrpc.jsonrpc_app import CallContextBuilder
from a2a.server.context import ServerCallContext
from a2a.server.events.in_memory_queue_manager import InMemoryQueueManager
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler

from opensensa.a2a.agent_card import build_agent_card
from opensensa.a2a.executor import FrameworkAgentExecutor
from opensensa.a2a.task_store import InMemoryTaskStore
from opensensa.config import AppConfig
from opensensa.orchestrator.agent_registry import AgentRegistry

logger = logging.getLogger("opensensa.orchestrator")

# Headers to propagate from inbound HTTP requests into ServerCallContext.state
_PROPAGATED_HEADERS = ("x-a2a-depth", "x-a2a-client-request-id")


class _HeaderCallContextBuilder(CallContextBuilder):
    """Extracts selected HTTP headers into ``ServerCallContext.state``.

    This lets the executor read headers like ``X-A2A-Depth`` and
    ``X-A2A-Client-Request-Id`` that were sent by the ``delegate``
    tool on the calling agent's side.

    On the **first hop** (client → agent), ``X-A2A-Client-Request-Id``
    is not yet present as an HTTP header — the client's id is only in
    the JSON-RPC body.  In that case we seed it from the cached request
    body (which the a2a-sdk has already read before calling ``build()``).
    """

    def build(self, request: Request) -> ServerCallContext:
        state: dict[str, Any] = {}
        for hdr in _PROPAGATED_HEADERS:
            value = request.headers.get(hdr)
            if value is not None:
                state[hdr] = value

        # Seed client request id from JSON-RPC body on the first hop.
        # By the time build() is called the a2a-sdk has already done
        # ``await request.body()`` which caches the bytes on the Request.
        if "x-a2a-client-request-id" not in state:
            try:
                import json as _json
                body_bytes = getattr(request, "_body", None)
                if body_bytes:
                    data = _json.loads(body_bytes)
                    jsonrpc_id = data.get("id")
                    if jsonrpc_id is not None:
                        state["x-a2a-client-request-id"] = str(jsonrpc_id)
            except Exception:
                pass

        return ServerCallContext(state=state)


def create_orchestrator_app(
    config: AppConfig,
    agent_registry: AgentRegistry,
    mcp_server_url: str | None = None,
    enable_web: bool = True,
) -> FastAPI:
    """Create the FastAPI application with per-agent A2A sub-apps.

    Each agent defined in the registry gets its own:
      - ``A2AFastAPIApplication`` mounted at ``/agents/{name}/``
      - ``AgentCard`` with ``url`` pointing to the sub-app
      - ``FrameworkAgentExecutor`` (hardcoded to that agent)
      - ``DefaultRequestHandler`` + ``InMemoryTaskStore`` + ``InMemoryQueueManager``

    Args:
        config: Framework configuration.
        agent_registry: Registry of local agent definitions.
        mcp_server_url: URL of the MCP tool server. Defaults to config-derived URL.

    Returns:
        FastAPI app ready to serve.
    """
    app = FastAPI(title="Agent Server", version="0.1.0")

    base_url = config.server.local_base_url

    if mcp_server_url is None:
        mcp_server_url = f"http://localhost:{config.server.mcp_port}/mcp"

    agents = agent_registry.list_agents()

    # Shared context builder that extracts HTTP headers into ServerCallContext
    context_builder = _HeaderCallContextBuilder()

    # Mount one A2AFastAPIApplication per agent
    for agent_def in agents:
        agent_card = build_agent_card(agent_def, base_url)
        executor = FrameworkAgentExecutor(
            agent_name=agent_def.name,
            agent_registry=agent_registry,
            config=config,
            mcp_server_url=mcp_server_url,
        )
        handler = DefaultRequestHandler(
            agent_executor=executor,
            task_store=InMemoryTaskStore(),
            queue_manager=InMemoryQueueManager(),
        )
        a2a_sub = A2AFastAPIApplication(
            agent_card=agent_card,
            http_handler=handler,
            context_builder=context_builder,
        )
        sub_app = a2a_sub.build()
        app.mount(f"/agents/{agent_def.name}", sub_app)
        logger.info(f"Mounted A2A sub-app for agent '{agent_def.name}' at /agents/{agent_def.name}/")

    logger.info(
        f"A2A server configured with {len(agents)} agent(s): "
        f"{[a.name for a in agents]}"
    )

    # --- Web frontend ---
    if enable_web:
        try:
            from starlette.middleware.cors import CORSMiddleware

            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            )

            from opensensa.web.routes import create_web_router

            web_router = create_web_router(
                config=config,
                registry=agent_registry,
                mcp_server_url=mcp_server_url,
            )
            app.include_router(web_router)
            logger.info(f"Web UI enabled at {config.server.local_base_url}/web")
        except Exception:
            logger.warning("Failed to enable web UI", exc_info=True)

    # --- Convenience endpoints (non-A2A) ---

    @app.get("/health")
    async def health():
        return {"status": "ok", "agents": agent_registry.agent_names()}

    @app.get("/agents")
    async def list_agents_endpoint():
        """List all local agents with their metadata and A2A URLs."""
        current_agents = agent_registry.list_agents()
        return [
            {
                "name": a.name,
                "description": a.description,
                "url": f"{base_url}/agents/{a.name}",
                "model": a.model,
                "tools": a.tools,
                "skills": [
                    {"id": s.id, "name": s.name, "description": s.description}
                    for s in a.skills
                ],
            }
            for a in current_agents
        ]

    return app
