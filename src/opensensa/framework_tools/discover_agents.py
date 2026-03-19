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

"""Framework tool: discover_agents — fetches A2A Agent Cards from remote + local agents."""

import logging
from typing import Any

import httpx

logger = logging.getLogger("opensensa.framework_tools")


def register(
    mcp,
    *,
    agent_registry=None,
    remote_agents: list[dict] | None = None,
    local_base_url: str = "http://localhost:8000",
):
    """Register the discover_agents tool.

    Args:
        mcp: The MCP server instance to register against.
        agent_registry: AgentRegistry instance for local agents.
        remote_agents: List of {"url": "..."} dicts for remote A2A agents.
        local_base_url: Base URL of the local A2A server for building local agent URLs.
    """

    @mcp.tool(
        title="Discover Agents",
        description=(
            "Discover available AI agents — both local and remote. Returns agent names, "
            "descriptions, skills, and capabilities. Use this to find agents that can "
            "handle specific tasks before delegating with send_to_agent."
        ),
        tags=["framework", "a2a", "discovery"],
    )
    async def discover_agents() -> list[dict[str, Any]]:
        """Fetch A2A Agent Cards from local registry and remote URLs."""
        agents: list[dict[str, Any]] = []

        # Local agents from filesystem — each has a URL at /agents/{name}
        if agent_registry:
            for defn in agent_registry.list_agents():
                agents.append({
                    "name": defn.name,
                    "description": defn.description,
                    "skills": [
                        {"id": s.id, "name": s.name, "description": s.description, "tags": s.tags}
                        for s in defn.skills
                    ],
                    "source": "local",
                    "url": f"{local_base_url.rstrip('/')}/agents/{defn.name}",
                })

        # Remote agents via A2A Agent Card discovery
        for entry in (remote_agents or []):
            url = entry.get("url", "").rstrip("/")
            if not url:
                continue
            card_url = f"{url}/.well-known/agent-card.json"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(card_url)
                    resp.raise_for_status()
                    card = resp.json()
                    agents.append({
                        "name": card.get("name", "unknown"),
                        "description": card.get("description", ""),
                        "skills": card.get("skills", []),
                        "source": "remote",
                        "url": url,
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch Agent Card from {card_url}: {e}")
                agents.append({
                    "name": f"unreachable ({url})",
                    "description": f"Could not fetch Agent Card: {e}",
                    "skills": [],
                    "source": "remote",
                    "url": url,
                })

        return agents
