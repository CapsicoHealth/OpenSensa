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

"""FastAPI routes for the OpenSensa web frontend.

Provides:
  - Static file serving + index.html
  - Agent CRUD REST endpoints

Chat messaging goes directly to the A2A endpoints at /agents/{name}/
using JSON-RPC message/stream — no server-side session management.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from opensensa.config import AppConfig
from opensensa.orchestrator.agent_registry import AgentRegistry

logger = logging.getLogger("opensensa.web")

# Directory containing static assets (app.js, styles.css)
_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATE_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class CreateAgentRequest(BaseModel):
    name: str
    description: str
    system_prompt: str
    model: str = "${default}"
    tools: list[str] = []
    sub_agents: list[str] = []


class EditAgentRequest(BaseModel):
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    tools: Optional[list[str]] = None
    sub_agents: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def create_web_router(
    config: AppConfig,
    registry: AgentRegistry,
    mcp_server_url: str,
) -> APIRouter:
    """Build and return the web frontend APIRouter."""

    router = APIRouter()
    agents_dir = Path(config.agents.directory).resolve()

    # -- Static files + index -----------------------------------------------

    @router.get("/web", response_class=HTMLResponse)
    async def serve_index():
        """Serve the main chat UI."""
        index_file = _TEMPLATE_DIR / "index.html"
        if not index_file.exists():
            raise HTTPException(status_code=404, detail="index.html not found")
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))

    @router.get("/web/static/{file_path:path}")
    async def serve_static(file_path: str):
        """Serve static JS/CSS files."""
        full_path = _STATIC_DIR / file_path
        if not full_path.exists() or not full_path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        # Determine content type
        suffix = full_path.suffix.lower()
        content_types = {
            ".js": "application/javascript",
            ".css": "text/css",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }
        media_type = content_types.get(suffix, "application/octet-stream")
        return FileResponse(full_path, media_type=media_type)

    # -- Agent listing (reuses registry) -------------------------------------

    @router.get("/api/agents")
    async def list_agents():
        """List all available agents."""
        registry.scan()  # Re-scan to pick up new/edited agents
        agents = registry.list_agents()
        return [
            {
                "name": a.name,
                "description": a.description,
                "model": a.model,
                "tools": a.tools,
                "sub_agents": getattr(a, "sub_agents", []) or [],
                "context_headers": getattr(a, "context_headers", []) or [],
                "skills": [
                    {"id": s.id, "name": s.name, "description": s.description}
                    for s in a.skills
                ],
            }
            for a in agents
        ]

    @router.get("/api/agents/{name}")
    async def get_agent(name: str):
        """Get details of a single agent, including system prompt."""
        registry.scan()
        agent_def = registry.get(name)
        if not agent_def:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return {
            "name": agent_def.name,
            "description": agent_def.description,
            "model": agent_def.model,
            "tools": agent_def.tools,
            "sub_agents": getattr(agent_def, "sub_agents", []) or [],
            "system_prompt": agent_def.system_prompt,
            "skills": [
                {"id": s.id, "name": s.name, "description": s.description}
                for s in agent_def.skills
            ],
        }

    # -- Agent CRUD ----------------------------------------------------------

    @router.post("/api/agents", status_code=201)
    async def create_agent(req: CreateAgentRequest):
        """Create a new agent .md file."""
        agents_dir.mkdir(parents=True, exist_ok=True)

        # Validate name
        name = req.name
        if len(name) <= 2 or not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", name):
            safe_name = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
            if not safe_name or len(safe_name) < 2:
                raise HTTPException(status_code=400, detail=f"Invalid agent name: '{name}'")
            name = safe_name

        file_path = agents_dir / f"{name}.md"
        if file_path.exists():
            raise HTTPException(status_code=409, detail=f"Agent '{name}' already exists")

        frontmatter: dict[str, Any] = {
            "name": name,
            "description": req.description,
            "model": req.model,
        }
        if req.tools:
            frontmatter["tools"] = req.tools
        if req.sub_agents:
            frontmatter["sub_agents"] = req.sub_agents

        yaml_block = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
        content = f"---\n{yaml_block}\n---\n\n{req.system_prompt.strip()}\n"
        file_path.write_text(content, encoding="utf-8")

        registry.scan()
        return {"status": "created", "name": name}

    @router.put("/api/agents/{name}")
    async def edit_agent(name: str, req: EditAgentRequest):
        """Edit an existing agent."""
        import frontmatter as fm

        file_path = agents_dir / f"{name}.md"
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        try:
            post = fm.load(str(file_path))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to parse agent file: {e}")

        meta = post.metadata
        updated_fields: list[str] = []

        if req.description is not None:
            meta["description"] = req.description
            updated_fields.append("description")
        if req.model is not None:
            meta["model"] = req.model
            updated_fields.append("model")
        if req.tools is not None:
            meta["tools"] = req.tools
            updated_fields.append("tools")
        if req.sub_agents is not None:
            meta["sub_agents"] = req.sub_agents
            updated_fields.append("sub_agents")

        body = post.content.strip()
        if req.system_prompt is not None:
            body = req.system_prompt.strip()
            updated_fields.append("system_prompt")

        if not updated_fields:
            return {"status": "no_changes", "name": name}

        yaml_block = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
        content = f"---\n{yaml_block}\n---\n\n{body}\n"
        file_path.write_text(content, encoding="utf-8")

        registry.scan()
        return {"status": "updated", "name": name, "updated_fields": updated_fields}

    @router.delete("/api/agents/{name}")
    async def delete_agent(name: str):
        """Delete an agent .md file."""
        file_path = agents_dir / f"{name}.md"
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        try:
            file_path.unlink()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")

        registry.scan()
        return {"status": "deleted", "name": name}

    return router
