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

"""Framework tool: edit_agent — modifies an existing agent .md file."""

import logging
import re
from pathlib import Path
from typing import Any, Optional

import frontmatter
import yaml

logger = logging.getLogger("opensensa.framework_tools")


def register(mcp, *, agents_directory: str | Path | None = None):
    """Register the edit_agent tool.

    Args:
        mcp: The MCP server instance.
        agents_directory: Path where agent .md files are stored.
    """

    @mcp.tool(
        title="Edit Agent",
        description=(
            "Edit an existing AI agent's definition. You can update its description, "
            "model, tools, and/or system prompt. Only the fields you provide will be "
            "changed — omitted fields are left as-is. The agent picks up changes "
            "immediately without restart."
        ),
        tags=["framework", "meta", "agent-management"],
    )
    def edit_agent(
        name: str,
        description: Optional[str] = None,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        tools: Optional[list[str]] = None,
        sub_agents: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Edit an existing agent .md file in the agents directory.

        Args:
            name: Name of the agent to edit (must already exist).
            description: New one-line description (or None to keep current).
            system_prompt: New system prompt / markdown body (or None to keep current).
            model: New model reference (or None to keep current).
            tools: New list of tool names (or None to keep current).
            sub_agents: New list of sub-agent names (or None to keep current).

        Returns:
            Confirmation dict with file path and updated fields, or error.
        """
        if not agents_directory:
            return {"error": "Agents directory not configured"}

        agents_dir = Path(agents_directory).resolve()
        file_path = agents_dir / f"{name}.md"

        if not file_path.exists():
            return {"error": f"Agent '{name}' not found at {file_path}"}

        # Parse existing file
        try:
            post = frontmatter.load(str(file_path))
        except Exception as e:
            return {"error": f"Failed to parse agent file: {e}"}

        meta = post.metadata
        updated_fields: list[str] = []

        # Apply updates — only for fields that were explicitly provided
        if description is not None:
            meta["description"] = description
            updated_fields.append("description")
        if model is not None:
            meta["model"] = model
            updated_fields.append("model")
        if tools is not None:
            meta["tools"] = tools
            updated_fields.append("tools")
        if sub_agents is not None:
            meta["sub_agents"] = sub_agents
            updated_fields.append("sub_agents")

        body = post.content.strip()
        if system_prompt is not None:
            body = system_prompt.strip()
            updated_fields.append("system_prompt")

        if not updated_fields:
            return {"status": "no_changes", "name": name, "message": "No fields were provided to update."}

        # Rebuild the file
        yaml_block = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
        content = f"---\n{yaml_block}\n---\n\n{body}\n"

        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Edited agent: {name} at {file_path} — updated: {updated_fields}")

        return {
            "status": "updated",
            "name": name,
            "file_path": str(file_path),
            "updated_fields": updated_fields,
            "message": f"Agent '{name}' has been updated ({', '.join(updated_fields)}).",
        }
