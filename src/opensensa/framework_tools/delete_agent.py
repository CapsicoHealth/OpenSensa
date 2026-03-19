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

"""Framework tool: delete_agent — removes an agent .md file from the agents directory."""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("opensensa.framework_tools")


def register(mcp, *, agents_directory: str | Path | None = None):
    """Register the delete_agent tool.

    Args:
        mcp: The MCP server instance.
        agents_directory: Path where agent .md files are stored.
    """

    @mcp.tool(
        title="Delete Agent",
        description=(
            "Delete an existing AI agent by removing its .md definition file. "
            "This is irreversible — the agent will no longer be available. "
            "The change takes effect immediately without restart."
        ),
        tags=["framework", "meta", "agent-management"],
    )
    def delete_agent(
        name: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Delete an agent .md file from the agents directory.

        Args:
            name: Name of the agent to delete (must already exist).
            confirm: Must be True to actually delete. Safety guard against accidental deletion.

        Returns:
            Confirmation dict or error.
        """
        if not agents_directory:
            return {"error": "Agents directory not configured"}

        agents_dir = Path(agents_directory).resolve()
        file_path = agents_dir / f"{name}.md"

        if not file_path.exists():
            return {"error": f"Agent '{name}' not found at {file_path}"}

        if not confirm:
            return {
                "status": "confirmation_required",
                "name": name,
                "file_path": str(file_path),
                "message": (
                    f"Are you sure you want to delete agent '{name}'? "
                    f"This will remove {file_path}. "
                    f"Call delete_agent again with confirm=True to proceed."
                ),
            }

        try:
            file_path.unlink()
        except Exception as e:
            return {"error": f"Failed to delete agent file: {e}"}

        logger.info(f"Deleted agent: {name} at {file_path}")

        return {
            "status": "deleted",
            "name": name,
            "file_path": str(file_path),
            "message": f"Agent '{name}' has been deleted.",
        }
