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

"""OpenSensa CLI — Click-based command-line interface.

Commands:
  opensensa                         — interactive chat (default)
  opensensa chat [agent]            — chat with an agent interactively
  opensensa init [dir]              — scaffold a new project
  opensensa serve                   — start MCP + A2A servers (headless)
  opensensa add-tool <name>         — generate tool skeleton
  opensensa add-agent <name>        — generate agent skeleton
  opensensa list-tools              — list MCP tools
  opensensa list-agents             — list agents
  opensensa test                    — smoke test
"""

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Optional

import click

# Package root for bundled files
_PACKAGE_ROOT = Path(__file__).parent


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.version_option(package_name="opensensa")
@click.pass_context
def cli(ctx):
    """OpenSensa — AI agent framework with A2A + MCP."""
    # Load .env FIRST, before any command touches config or env vars.
    # override=True so the .env always wins over stale shell exports.
    # usecwd=True is CRITICAL — without it find_dotenv() walks up from
    # cli.py's install location, not the user's project directory.
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True), override=True)

    if ctx.invoked_subcommand is None:
        ctx.invoke(chat)


# ---------------------------------------------------------------------------
# opensensa init
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("directory", default=".")
def init(directory: str):
    """Scaffold a new OpenSensa project.

    Creates opensensa.yaml, agents/ with Agent Creator, and tools/ with sample tools.
    """
    project_dir = Path(directory).resolve()

    click.echo(f"Initializing OpenSensa project in {project_dir}")

    project_dir.mkdir(parents=True, exist_ok=True)

    # --- opensensa.yaml ---
    config_dest = project_dir / "opensensa.yaml"
    if config_dest.exists():
        click.echo(f"  [skip] opensensa.yaml already exists")
    else:
        config_src = _PACKAGE_ROOT.parent.parent.parent / "opensensa.example.yaml"
        if not config_src.exists():
            # Fallback: generate inline
            config_dest.write_text(_default_config(), encoding="utf-8")
        else:
            shutil.copy2(config_src, config_dest)
        click.echo(f"  [created] opensensa.yaml")

    # --- agents/ directory + bundled agents ---
    agents_dir = project_dir / "agents"
    agents_dir.mkdir(exist_ok=True)

    bundled_agents_dir = _PACKAGE_ROOT / "agents"
    if bundled_agents_dir.exists():
        for md_file in bundled_agents_dir.glob("*.md"):
            dest = agents_dir / md_file.name
            if dest.exists():
                click.echo(f"  [skip] agents/{md_file.name} already exists")
            else:
                shutil.copy2(md_file, dest)
                click.echo(f"  [created] agents/{md_file.name}")
    else:
        click.echo(f"  [warn] No bundled agents found at {bundled_agents_dir}")

    # --- tools/ directory + bundled example tools ---
    tools_dir = project_dir / "tools"
    tools_dir.mkdir(exist_ok=True)

    bundled_tools_dir = _PACKAGE_ROOT / "tools"
    if bundled_tools_dir.exists():
        for py_file in bundled_tools_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            dest = tools_dir / py_file.name
            if dest.exists():
                click.echo(f"  [skip] tools/{py_file.name} already exists")
            else:
                shutil.copy2(py_file, dest)
                click.echo(f"  [created] tools/{py_file.name}")
    else:
        click.echo(f"  [warn] No bundled tools found at {bundled_tools_dir}")

    # --- .env skeleton ---
    env_file = project_dir / ".env"
    if not env_file.exists():
        env_file.write_text(
            "# OpenSensa environment variables\n"
            "# OPENAI_API_KEY=sk-...\n",
            encoding="utf-8",
        )
        click.echo(f"  [created] .env")

    click.echo()
    click.echo("Done! Next steps:")
    click.echo(f"  cd {project_dir}")
    click.echo("  # Edit opensensa.yaml with your model endpoint")
    click.echo("  # Set OPENAI_API_KEY in .env or environment")
    click.echo("  opensensa serve")


# ---------------------------------------------------------------------------
# opensensa serve
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--host", default=None, help="Override bind host.")
@click.option("--mcp-port", default=None, type=int, help="Override MCP server port.")
@click.option("--orchestrator-port", default=None, type=int, help="Override orchestrator port.")
@click.option("--config", "config_path", default=None, help="Path to opensensa.yaml.")
@click.option("--reload", is_flag=True, help="Auto-reload on file changes.")
@click.option("--web/--no-web", default=True, help="Enable/disable the web UI (default: enabled).")
def serve(host, mcp_port, orchestrator_port, config_path, reload, web):
    """Start the MCP tool server and A2A agent server (headless)."""
    from opensensa.config import load_config
    from opensensa.utils.logging import setup_logging

    config = load_config(config_path)
    setup_logging(config.logging.level, config.logging.file)

    # Apply overrides
    if host:
        config.server.host = host
    if mcp_port:
        config.server.mcp_port = mcp_port
    if orchestrator_port:
        config.server.orchestrator_port = orchestrator_port

    _start_both(config, reload=reload, enable_web=web)


def _start_mcp_server(config, reload: bool = False):
    """Start only the MCP tool server."""
    import uvicorn

    from opensensa.mcp_server.server import create_mcp_server
    from opensensa.mcp_server.tool_loader import discover_and_load_tools

    click.echo(f"Starting MCP server on {config.server.host}:{config.server.mcp_port}")

    mcp = create_mcp_server(
        host=config.server.host,
        port=config.server.mcp_port,
    )

    # Register framework tools
    _register_framework_tools(mcp, config)

    # Load user tools
    tools_dir = Path(config.tools.directory).resolve()
    discover_and_load_tools(tools_dir, mcp)

    # Run via FastMCP's built-in server
    mcp.run(transport="streamable-http")


def _start_orchestrator(config, reload: bool = False, enable_web: bool = True):
    """Start the A2A orchestrator with per-agent sub-apps."""
    import uvicorn

    from opensensa.orchestrator.agent_registry import AgentRegistry
    from opensensa.orchestrator.server import create_orchestrator_app

    agents_dir = Path(config.agents.directory).resolve()
    registry = AgentRegistry(agents_dir)
    registry.scan()

    mcp_server_url = f"http://localhost:{config.server.mcp_port}/mcp"

    click.echo(f"Starting A2A server on {config.server.host}:{config.server.orchestrator_port}")
    click.echo(f"Agents: {registry.agent_names()}")
    for name in registry.agent_names():
        click.echo(f"  /agents/{name}/")
    if enable_web:
        advertise_host = "localhost" if config.server.host == "0.0.0.0" else config.server.host
        click.echo(f"  Web UI: http://{advertise_host}:{config.server.orchestrator_port}/web")

    app = create_orchestrator_app(config, registry, mcp_server_url=mcp_server_url, enable_web=enable_web)

    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.orchestrator_port,
        log_level=config.logging.level,
        reload=reload,
    )


def _start_both(config, reload: bool = False, enable_web: bool = True):
    """Start both MCP and orchestrator servers in separate processes."""
    import multiprocessing

    from opensensa.orchestrator.agent_registry import AgentRegistry

    agents_dir = Path(config.agents.directory).resolve()
    registry = AgentRegistry(agents_dir)
    agent_names = registry.agent_names()

    click.echo("Starting OpenSensa servers:")
    click.echo(f"  MCP tool server:  {config.server.host}:{config.server.mcp_port}")
    click.echo(f"  A2A agent server: {config.server.host}:{config.server.orchestrator_port}")
    for name in agent_names:
        click.echo(f"    /agents/{name}/")
    if enable_web:
        advertise_host = "localhost" if config.server.host == "0.0.0.0" else config.server.host
        click.echo(f"  Web UI: http://{advertise_host}:{config.server.orchestrator_port}/web")
    click.echo()

    mcp_proc = multiprocessing.Process(
        target=_start_mcp_server,
        args=(config,),
        kwargs={"reload": reload},
        daemon=True,
    )
    orch_proc = multiprocessing.Process(
        target=_start_orchestrator,
        args=(config,),
        kwargs={"reload": reload, "enable_web": enable_web},
        daemon=True,
    )

    mcp_proc.start()
    orch_proc.start()

    try:
        click.echo("Press Ctrl+C to stop both servers.")
        mcp_proc.join()
        orch_proc.join()
    except KeyboardInterrupt:
        click.echo("\nShutting down...")
        mcp_proc.terminate()
        orch_proc.terminate()
        mcp_proc.join(timeout=5)
        orch_proc.join(timeout=5)
        click.echo("Stopped.")


# ---------------------------------------------------------------------------
# opensensa add-tool
# ---------------------------------------------------------------------------

@cli.command("add-tool")
@click.argument("name")
@click.option("--config", "config_path", default=None, help="Path to opensensa.yaml.")
def add_tool(name: str, config_path: Optional[str]):
    """Generate a tool skeleton file."""
    from opensensa.config import load_config

    config = load_config(config_path)
    tools_dir = Path(config.tools.directory).resolve()
    tools_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize name
    safe_name = name.replace("-", "_").replace(" ", "_").lower()
    file_path = tools_dir / f"{safe_name}.py"

    if file_path.exists():
        click.echo(f"Error: {file_path} already exists", err=True)
        sys.exit(1)

    file_path.write_text(
        f'"""Tool: {name}\n'
        f'\n'
        f'Drop this file into your tools/ directory. The @mcp.tool() decorator\n'
        f'registers it automatically when the MCP server starts.\n'
        f'"""\n'
        f'\n'
        f'from fastmcp import FastMCP\n'
        f'\n'
        f'# This will be set by the tool loader — do not call get_mcp() at import time.\n'
        f'# Just define your register() function and the framework will call it.\n'
        f'\n'
        f'\n'
        f'def register(mcp: FastMCP):\n'
        f'    """Register the {safe_name} tool. Called automatically by the tool loader."""\n'
        f'\n'
        f'    @mcp.tool(\n'
        f'        title="{name.replace("_", " ").title()}",\n'
        f'        description="TODO: describe what this tool does",\n'
        f'    )\n'
        f'    async def {safe_name}(query: str) -> str:\n'
        f'        """TODO: implement this tool."""\n'
        f'        return f"Result for: {{query}}"\n',
        encoding="utf-8",
    )

    click.echo(f"Created tool skeleton: {file_path}")


# ---------------------------------------------------------------------------
# opensensa add-agent
# ---------------------------------------------------------------------------

@cli.command("add-agent")
@click.argument("name")
@click.option("--config", "config_path", default=None, help="Path to opensensa.yaml.")
def add_agent(name: str, config_path: Optional[str]):
    """Generate an agent skeleton .md file."""
    from opensensa.config import load_config

    config = load_config(config_path)
    agents_dir = Path(config.agents.directory).resolve()
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize name to kebab-case
    safe_name = name.replace("_", "-").replace(" ", "-").lower()
    file_path = agents_dir / f"{safe_name}.md"

    if file_path.exists():
        click.echo(f"Error: {file_path} already exists", err=True)
        sys.exit(1)

    file_path.write_text(
        f"---\n"
        f"name: {safe_name}\n"
        f"description: TODO — describe what this agent does\n"
        f"model: ${{default}}\n"
        f"tools: []\n"
        f"sub_agents: []\n"
        f"skills:\n"
        f"  - id: {safe_name}-skill\n"
        f"    name: {name.replace('-', ' ').replace('_', ' ').title()}\n"
        f"    description: TODO — describe this skill\n"
        f"    tags: []\n"
        f"input_modes: [\"text/plain\"]\n"
        f"output_modes: [\"text/plain\"]\n"
        f"---\n"
        f"\n"
        f"# {name.replace('-', ' ').replace('_', ' ').title()}\n"
        f"\n"
        f"You are a helpful assistant that specializes in...\n"
        f"\n"
        f"## Guidelines\n"
        f"- TODO: add guidelines\n",
        encoding="utf-8",
    )

    click.echo(f"Created agent skeleton: {file_path}")


# ---------------------------------------------------------------------------
# opensensa list-tools
# ---------------------------------------------------------------------------

@cli.command("list-tools")
@click.option("--config", "config_path", default=None, help="Path to opensensa.yaml.")
def list_tools(config_path: Optional[str]):
    """List available MCP tools."""
    from opensensa.config import load_config
    from opensensa.mcp_server.server import create_mcp_server
    from opensensa.mcp_server.tool_loader import discover_and_load_tools

    config = load_config(config_path)

    mcp = create_mcp_server(enable_logging=False)
    _register_framework_tools(mcp, config)

    tools_dir = Path(config.tools.directory).resolve()
    discover_and_load_tools(tools_dir, mcp)

    if hasattr(mcp, "registered_tools"):
        tools = mcp.registered_tools
        if not tools:
            click.echo("No tools registered.")
            return
        click.echo(f"{'Tool':<30} {'Title':<30} {'Tags'}")
        click.echo("-" * 90)
        for name, meta in sorted(tools.items()):
            title = meta.get("title", "") or ""
            tags = ", ".join(meta.get("tags", []))
            click.echo(f"{meta.get('function', name):<30} {title:<30} {tags}")
    else:
        click.echo("Tool introspection not available (LoggedMCP not enabled)")


# ---------------------------------------------------------------------------
# opensensa list-agents
# ---------------------------------------------------------------------------

@cli.command("list-agents")
@click.option("--config", "config_path", default=None, help="Path to opensensa.yaml.")
def list_agents(config_path: Optional[str]):
    """List local and remote agents."""
    from opensensa.config import load_config
    from opensensa.orchestrator.agent_registry import AgentRegistry

    config = load_config(config_path)
    agents_dir = Path(config.agents.directory).resolve()
    registry = AgentRegistry(agents_dir)

    agents = registry.list_agents()
    if not agents:
        click.echo("No agents found.")
        click.echo(f"(Looked in: {agents_dir})")
        return

    click.echo(f"{'Agent':<25} {'Model':<20} {'Tools':<30} {'Description'}")
    click.echo("-" * 110)
    for a in agents:
        tools_str = ", ".join(a.tools[:3])
        if len(a.tools) > 3:
            tools_str += f" (+{len(a.tools) - 3})"
        click.echo(f"{a.name:<25} {a.model:<20} {tools_str:<30} {a.description[:40]}")

    # Remote agents
    if config.remote_agents:
        click.echo()
        click.echo("Remote agents:")
        for ra in config.remote_agents:
            click.echo(f"  {ra.url}")


# ---------------------------------------------------------------------------
# opensensa test
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--config", "config_path", default=None, help="Path to opensensa.yaml.")
def test(config_path: Optional[str]):
    """Run a quick smoke test — list tools and agents."""
    from opensensa.config import load_config
    from opensensa.orchestrator.agent_registry import AgentRegistry

    config = load_config(config_path)

    # Check config  
    click.echo("Configuration:")
    click.echo(f"  Models: {list(config.models.registry.keys())}")
    click.echo(f"  Default model: {config.models.default}")
    click.echo(f"  MCP port: {config.server.mcp_port}")
    click.echo(f"  Orchestrator port: {config.server.orchestrator_port}")
    click.echo()

    # Check agents
    agents_dir = Path(config.agents.directory).resolve()
    registry = AgentRegistry(agents_dir)
    agents = registry.list_agents()
    click.echo(f"Agents ({len(agents)}):")
    for a in agents:
        click.echo(f"  {a.name}: {a.description}")
    click.echo()

    # Check tools directory
    tools_dir = Path(config.tools.directory).resolve()
    if tools_dir.exists():
        tool_files = list(tools_dir.glob("*.py"))
        click.echo(f"Tool files ({len(tool_files)}):")
        for f in tool_files:
            if not f.name.startswith("_"):
                click.echo(f"  {f.name}")
    else:
        click.echo(f"Tools directory not found: {tools_dir}")

    click.echo()
    click.echo("Smoke test passed.")


# ---------------------------------------------------------------------------
# opensensa chat (interactive mode — the DEFAULT command)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("agent_name", default=None, required=False)
@click.option("--config", "config_path", default=None, help="Path to opensensa.yaml.")
def chat(agent_name: Optional[str], config_path: Optional[str]):
    """Start an interactive chat session with an agent.

    If AGENT_NAME is omitted the CLI will auto-select (when only one agent
    exists) or show a picker.
    """
    from opensensa.config import load_config, resolve_model
    from opensensa.orchestrator.agent_registry import AgentRegistry
    from opensensa.utils.logging import setup_logging

    config = load_config(config_path)
    setup_logging(config.logging.level, config.logging.file, console_output=False)

    # Validate that every model has a usable API key before starting
    for model_name, model_cfg in config.models.registry.items():
        key = model_cfg.api_key or ""
        if key.startswith("${") or not key.strip():
            click.echo()
            click.echo(f"  \033[1;31m✖ Error:\033[0m API key for model '{model_name}' is not set.")
            click.echo(f"    The config has: api_key: {key or '(empty)'}")
            click.echo()
            click.echo("    Fix: set the key in your .env file or shell environment:")
            click.echo(f"      echo 'OPENAI_API_KEY=sk-...' >> .env")
            click.echo()
            sys.exit(1)

    agents_dir = Path(config.agents.directory).resolve()
    registry = AgentRegistry(agents_dir)

    from opensensa.interactive.chat import start_chat

    asyncio.run(start_chat(config, registry, agent_name))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_framework_tools(mcp, config):
    """Register the 4 framework-provided MCP tools."""
    from opensensa.orchestrator.agent_registry import AgentRegistry

    agents_dir = Path(config.agents.directory).resolve()
    registry = AgentRegistry(agents_dir)

    remote_agents = [{"url": ra.url} for ra in config.remote_agents]

    # Build local base URL so discover_agents can return reachable URLs
    advertise_host = "localhost" if config.server.host == "0.0.0.0" else config.server.host
    local_base_url = f"http://{advertise_host}:{config.server.orchestrator_port}"

    # Import and register each framework tool
    from opensensa.framework_tools import discover_agents, send_to_agent, create_agent, edit_agent, delete_agent, list_tools

    discover_agents.register(
        mcp,
        agent_registry=registry,
        remote_agents=remote_agents,
        local_base_url=local_base_url,
    )
    send_to_agent.register(mcp)
    # NOTE: delegate is NOT registered on MCP — it is a native FunctionTool
    # wired directly into the Agent by agent_builder.py (A2A, not MCP).
    create_agent.register(mcp, agents_directory=config.agents.directory)
    edit_agent.register(mcp, agents_directory=config.agents.directory)
    delete_agent.register(mcp, agents_directory=config.agents.directory)
    list_tools.register(mcp)


def _default_config() -> str:
    """Generate default opensensa.yaml content inline."""
    return """\
# OpenSensa Configuration

models:
  default: my-model
  registry:
    my-model:
      base_url: https://api.openai.com/v1
      api_key: ${OPENAI_API_KEY}
      model_name: gpt-4.1-mini

server:
  host: 0.0.0.0
  orchestrator_port: 8000
  mcp_port: 8001

agents:
  directory: ./agents/

tools:
  directory: ./tools/
  builtin: true

logging:
  level: info
"""


if __name__ == "__main__":
    cli()
