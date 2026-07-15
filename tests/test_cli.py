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

"""Tests for the CLI commands."""

import tempfile
from pathlib import Path

from click.testing import CliRunner

from opensensa.cli import cli


def test_init_creates_structure():
    """opensensa init should create config, agents/, tools/."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "my-project"
        result = runner.invoke(cli, ["init", str(target)])
        assert result.exit_code == 0, result.output

        assert (target / "opensensa.yaml").exists()
        assert (target / "agents").is_dir()
        assert (target / "tools").is_dir()
        assert (target / ".env").exists()

        # Agent Creator should be copied
        assert (target / "agents" / "agent-manager.md").exists()


def test_init_idempotent():
    """Running init twice should not overwrite existing files."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        result1 = runner.invoke(cli, ["init", tmpdir])
        assert result1.exit_code == 0

        # Modify a file
        config = Path(tmpdir) / "opensensa.yaml"
        original = config.read_text()
        config.write_text(original + "\n# custom comment\n")

        # Re-run init
        result2 = runner.invoke(cli, ["init", tmpdir])
        assert result2.exit_code == 0
        assert "skip" in result2.output

        # File should be unchanged
        assert "# custom comment" in config.read_text()


def test_list_agents_empty():
    """list-agents with no agents dir should handle gracefully."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Path(tmpdir) / "opensensa.yaml"
        config.write_text("agents:\n  directory: ./nonexistent/\n")
        result = runner.invoke(cli, ["list-agents", "--config", str(config)])
        assert result.exit_code == 0
        assert "No agents found" in result.output


def test_test_command():
    """opensensa test should complete successfully with a valid project."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        # Init first
        runner.invoke(cli, ["init", tmpdir])

        # Run test from project dir
        result = runner.invoke(cli, ["test", "--config", str(Path(tmpdir) / "opensensa.yaml")])
        assert result.exit_code == 0
        assert "Smoke test passed" in result.output
