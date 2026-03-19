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

"""Framework tool: list_tools — returns all registered MCP tools with metadata."""

import logging
from typing import Any

logger = logging.getLogger("opensensa.framework_tools")


def register(mcp):
    """Register the list_tools tool.

    Args:
        mcp: The MCP server instance (LoggedMCP or FastMCP).
    """

    @mcp.tool(
        title="List Tools",
        description=(
            "List all available MCP tools with their names, descriptions, and tags. "
            "Use this to discover what capabilities are available before creating agents "
            "or deciding which tools to use."
        ),
        tags=["framework", "meta", "introspection"],
    )
    def list_tools() -> list[dict[str, Any]]:
        """Return metadata for all registered MCP tools."""
        tools_list: list[dict[str, Any]] = []

        # If it's a LoggedMCP wrapper, use its registered_tools property
        if hasattr(mcp, "registered_tools"):
            for tool_name, meta in mcp.registered_tools.items():
                tools_list.append({
                    "name": meta.get("function", tool_name),
                    "title": meta.get("title", tool_name),
                    "description": meta.get("description", ""),
                    "tags": meta.get("tags", []),
                })
        else:
            # Fallback: just report that introspection isn't available
            tools_list.append({
                "name": "list_tools",
                "title": "List Tools",
                "description": "Tool introspection (limited: raw FastMCP instance)",
                "tags": ["framework"],
            })

        return tools_list
