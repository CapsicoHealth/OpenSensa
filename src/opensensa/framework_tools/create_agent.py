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

"""Framework tool: create_agent — writes a new agent .md file to the agents directory."""

import logging
import re
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger("opensensa.framework_tools")


def register(mcp, *, agents_directory: str | Path | None = None):
    """Register the create_agent tool.

    Args:
        mcp: The MCP server instance.
        agents_directory: Path where agent .md files are written.
    """

    @mcp.tool(
        title="Create Agent",
        description=(
            "Create a new AI agent by writing a .md definition file. Provide the agent's "
            "name, description, model, tools, and system prompt. The agent becomes available "
            "immediately without restart."
        ),
        tags=["framework", "meta", "agent-creation"],
    )
    def create_agent(
        name: str,
        description: str,
        system_prompt: str,
        model: str = "${default}",
        tools: Optional[list[str]] = None,
        sub_agents: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Write a new agent .md file to the agents directory.

        Args:
            name: Agent name in kebab-case (e.g. "data-analyst").
            description: One-line description of what the agent does.
            system_prompt: The full system prompt (markdown body of the file).
            model: Model reference (default: "${default}").
            tools: List of tool names the agent should have access to.
            sub_agents: List of agent names this agent can delegate to via the delegate tool.

        Returns:
            Confirmation dict with file path and agent name.
        """
        if not agents_directory:
            return {"error": "Agents directory not configured"}

        agents_dir = Path(agents_directory).resolve()
        agents_dir.mkdir(parents=True, exist_ok=True)

        # Validate name — must be kebab-case (a-z, 0-9, hyphens)
        if len(name) <= 2 or not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", name):
            # Be lenient — sanitize instead of rejecting
            safe_name = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
            if not safe_name or len(safe_name) < 2:
                return {"error": f"Invalid agent name: '{name}'"}
            name = safe_name

        file_path = agents_dir / f"{name}.md"
        if file_path.exists():
            return {"error": f"Agent '{name}' already exists at {file_path}"}

        # Build frontmatter
        frontmatter: dict[str, Any] = {
            "name": name,
            "description": description,
            "model": model,
        }
        if tools:
            frontmatter["tools"] = tools
        if sub_agents:
            frontmatter["sub_agents"] = sub_agents

        # Write the file
        yaml_block = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
        content = f"---\n{yaml_block}\n---\n\n{system_prompt.strip()}\n"

        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Created agent: {name} at {file_path}")

        return {
            "status": "created",
            "name": name,
            "file_path": str(file_path),
            "message": f"Agent '{name}' is now available.",
        }
