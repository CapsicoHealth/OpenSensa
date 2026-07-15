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

"""Simple addition tool for testing MCP functionality."""


def register(mcp):
    """Register the add_numbers tool with the given MCP instance."""

    @mcp.tool(
        title="Add Numbers",
        description="Add two numbers together. A simple test tool for validating MCP functionality.",
        tags=["math", "arithmetic", "test"],
    )
    async def add_numbers(a: int, b: int) -> int:
        """Add two numbers and return the result."""
        return a + b
