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

"""MCP tool server — FastMCP with LoggedMCP wrapper.

Creates the MCP server instance that tool files register against.
Configured via AppConfig at startup time.
"""

import os
from typing import Optional


# Module-level MCP instance — set by create_mcp_server()
_mcp_instance = None


def get_mcp():
    """Get the current MCP server instance.

    Tools import this to register themselves:
        from opensensa.mcp_server.server import get_mcp
        mcp = get_mcp()

        @mcp.tool(...)
        def my_tool(...):
            ...
    """
    if _mcp_instance is None:
        raise RuntimeError(
            "MCP server not initialized. Call create_mcp_server() first, "
            "or use `opensensa serve` which does this automatically."
        )
    return _mcp_instance


def create_mcp_server(
    host: str = "0.0.0.0",
    port: int = 8001,
    name: str = "ToolServer",
    enable_logging: bool = True,
):
    """Create and configure the MCP server instance.

    Args:
        host: Bind address.
        port: Bind port.
        name: Server name shown to MCP clients.
        enable_logging: Whether to wrap with LoggedMCP for structured logging.

    Returns:
        The LoggedMCP (or raw FastMCP) instance ready for tool registration.
    """
    global _mcp_instance

    from mcp.server.fastmcp import FastMCP
    from opensensa.utils.logging import LoggedMCP

    # Required for dev/testing without auth
    os.environ.setdefault("DANGEROUSLY_OMIT_AUTH", "true")

    raw_mcp = FastMCP(name, host=host, port=port)

    if enable_logging:
        _mcp_instance = LoggedMCP(raw_mcp, enable_logging=True)
    else:
        _mcp_instance = raw_mcp

    return _mcp_instance
