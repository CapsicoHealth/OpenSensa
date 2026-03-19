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

"""Tests for MCP tool auto-discovery from the tools directory."""

import tempfile
from pathlib import Path

import pytest

from opensensa.mcp_server.tool_loader import discover_and_load_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_tools_dir():
    """Create a temp directory with sample tool files."""
    with tempfile.TemporaryDirectory() as d:
        tools_dir = Path(d) / "tools"
        tools_dir.mkdir()
        yield tools_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestToolLoader:
    def test_discover_empty_directory(self, tmp_tools_dir):
        """Empty tools directory should load zero modules."""
        loaded = discover_and_load_tools(tmp_tools_dir)
        assert loaded == []

    def test_discover_ignores_dunder_files(self, tmp_tools_dir):
        """Files starting with _ should be skipped."""
        (tmp_tools_dir / "__init__.py").write_text("# init\n")
        (tmp_tools_dir / "_private.py").write_text("# private\n")

        loaded = discover_and_load_tools(tmp_tools_dir)
        assert loaded == []

    def test_discover_loads_simple_module(self, tmp_tools_dir):
        """A plain .py file should be importable."""
        (tmp_tools_dir / "simple_tool.py").write_text(
            "LOADED = True\n"
        )

        loaded = discover_and_load_tools(tmp_tools_dir)
        assert "simple_tool" in loaded

    def test_discover_calls_register_function(self, tmp_tools_dir):
        """If module has register(mcp), it should be called with the MCP instance."""
        (tmp_tools_dir / "reg_tool.py").write_text(
            "registered_with = None\n"
            "\n"
            "def register(mcp):\n"
            "    global registered_with\n"
            "    registered_with = mcp\n"
        )

        sentinel = object()
        loaded = discover_and_load_tools(tmp_tools_dir, mcp_instance=sentinel)

        assert "reg_tool" in loaded

        # Verify register() was called with our MCP instance
        import sys
        mod = sys.modules.get("user_tools.reg_tool")
        assert mod is not None
        assert mod.registered_with is sentinel

    def test_discover_skips_register_without_mcp(self, tmp_tools_dir):
        """If no mcp_instance, register() should NOT be called (no crash)."""
        (tmp_tools_dir / "reg_tool2.py").write_text(
            "call_count = 0\n"
            "\n"
            "def register(mcp):\n"
            "    global call_count\n"
            "    call_count += 1\n"
        )

        loaded = discover_and_load_tools(tmp_tools_dir, mcp_instance=None)
        assert "reg_tool2" in loaded

        import sys
        mod = sys.modules.get("user_tools.reg_tool2")
        assert mod.call_count == 0

    def test_discover_handles_import_error(self, tmp_tools_dir):
        """A broken tool file should not crash the loader."""
        (tmp_tools_dir / "broken_tool.py").write_text(
            "import nonexistent_module_12345\n"
        )
        (tmp_tools_dir / "good_tool.py").write_text(
            "LOADED = True\n"
        )

        loaded = discover_and_load_tools(tmp_tools_dir)

        # good_tool should still load; broken_tool should be skipped
        assert "good_tool" in loaded
        assert "broken_tool" not in loaded

    def test_discover_nonexistent_directory(self):
        """Nonexistent directory should return empty list, not crash."""
        loaded = discover_and_load_tools("/tmp/nonexistent_tools_dir_12345")
        assert loaded == []

    def test_discover_multiple_tools_sorted(self, tmp_tools_dir):
        """Multiple tools should be loaded in alphabetical order."""
        (tmp_tools_dir / "z_last.py").write_text("ORDER = 'z'\n")
        (tmp_tools_dir / "a_first.py").write_text("ORDER = 'a'\n")
        (tmp_tools_dir / "m_middle.py").write_text("ORDER = 'm'\n")

        loaded = discover_and_load_tools(tmp_tools_dir)
        assert loaded == ["a_first", "m_middle", "z_last"]
