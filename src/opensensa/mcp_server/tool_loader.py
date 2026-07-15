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

"""Auto-discovers tool files from a directory and registers them with the MCP server.

Scans the configured tools directory for .py files, imports them, and any functions
decorated with @mcp.tool() are automatically registered.
"""

import importlib.util
import logging
import sys
from pathlib import Path

logger = logging.getLogger("opensensa.tools")


def discover_and_load_tools(tools_directory: str | Path, mcp_instance=None) -> list[str]:
    """Import all .py files in tools_directory so their @mcp.tool() decorators fire.

    Supports two tool registration patterns:
      1. Module has a ``register(mcp)`` function — called with the MCP instance.
      2. Module-level ``@mcp.tool()`` decorators that fire on import.

    Args:
        tools_directory: Absolute or relative path to the tools folder.
        mcp_instance: If provided, passed to ``register(mcp)`` if the module
                      defines it. Also set as module-level MCP instance so
                      ``from opensensa.mcp_server.server import get_mcp`` works.

    Returns:
        List of tool module names that were successfully loaded.
    """
    tools_dir = Path(tools_directory).resolve()

    if not tools_dir.exists():
        logger.warning(f"Tools directory does not exist: {tools_dir}")
        return []

    if not tools_dir.is_dir():
        logger.warning(f"Tools path is not a directory: {tools_dir}")
        return []

    loaded: list[str] = []

    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_name = f"user_tools.{py_file.stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                logger.warning(f"Could not create module spec for {py_file}")
                continue

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # If the module defines register(mcp), call it with the MCP instance
            if mcp_instance and hasattr(module, "register") and callable(module.register):
                module.register(mcp_instance)

            loaded.append(py_file.stem)
            logger.info(f"Loaded tool module: {py_file.name}")

        except Exception as e:
            logger.error(f"Failed to load tool {py_file.name}: {e}")

    logger.info(f"Discovered {len(loaded)} tool module(s) from {tools_dir}")
    return loaded
