<p align="center">
  <strong>OpenSensa</strong><br>
  <em>Build multi-agent systems with markdown files, MCP tools, and the A2A protocol.</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/opensensa/"><img alt="PyPI" src="https://img.shields.io/pypi/v/opensensa?color=blue"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue"></a>
  <a href="LICENSE"><img alt="Apache 2.0 License" src="https://img.shields.io/badge/license-Apache%202.0-green"></a>
</p>

---

OpenSensa is an open-source CLI framework for building, running, and orchestrating AI agents. Define each agent as a single markdown file, wire up tools as plain Python functions, point at any OpenAI-compatible LLM, and get a production-ready multi-agent system with full [A2A protocol](https://google.github.io/A2A/) compliance and [MCP](https://modelcontextprotocol.io/) tool serving — in minutes, not weeks.

## Why OpenSensa?

Most agent frameworks require you to learn complex SDKs, write pages of boilerplate, and lock yourself into a specific LLM provider. OpenSensa takes a different approach:

| Problem | OpenSensa's answer |
|---|---|
| **Agents are code-heavy to define** | Each agent is a **single `.md` file** — YAML frontmatter for config, markdown body for the system prompt. No Python classes, no inheritance hierarchies. |
| **Multi-agent communication is proprietary** | All agent-to-agent communication uses the **[A2A protocol](https://google.github.io/A2A/)** — the open standard for inter-agent messaging. Your agents are interoperable with Google ADK, LangGraph, CrewAI, or any A2A-compliant system. |
| **Tool integration is fragmented** | Tools are served over **[MCP](https://modelcontextprotocol.io/)** (Model Context Protocol). Write a Python function, decorate it, drop the file in a folder. Done. |
| **Locked to one LLM provider** | Works with **any OpenAI-compatible endpoint** — OpenAI, Ollama, vLLM, LM Studio, Together, Groq, Fireworks, and more. Switch models by editing one line in YAML. |
| **No observability out of the box** | Built-in **live call graph** in the terminal, **structured JSON logging**, and a **web UI** with real-time delegation tree visualization. |
| **Hard to go from prototype to production** | `opensensa chat` for development, `opensensa serve` for production. Same architecture, same agents, same tools. |

## Key Features

- **Agents as Markdown** — Each `.md` file with YAML frontmatter becomes a fully configured agent with an A2A endpoint, Agent Card, and SSE streaming support.
- **MCP for Tools, A2A for Agents** — Clean separation: tools use MCP, agent-to-agent communication uses A2A. Industry standards, not proprietary protocols.
- **Built-in Agent Manager** — Ships with a meta-agent that can create, edit, and delete other agents conversationally. Start a project, chat with the Agent Manager, and build your agent fleet without touching a file.
- **Explicit Delegation Graph** — Agents declare `sub_agents` in frontmatter. You can see exactly which agents can talk to which just by reading the `.md` files. Depth-limited (max 5 hops) to prevent infinite loops.
- **Live Call Graph** — Real-time Rich terminal tree showing tool calls (🔧), delegations (🤖), and LLM invocations (💬) with timing and token counts as they happen.
- **Web UI** — `opensensa serve --web` provides a browser-based chat interface with an agent sidebar, real-time delegation tree visualization, and agent CRUD.
- **Auto-Discovery** — Tools are auto-loaded from a directory; agents are scanned from the filesystem. Drop a file in, it's live — no restart needed.
- **Any LLM** — Single `OpenAIChatCompletionsModel` path works with any provider exposing `/v1/chat/completions`.
- **Structured Tracing** — Every LLM call, tool invocation, and delegation is logged as structured JSON with timing and token usage.

## Quick Start

### Installation

```bash
pip install opensensa
```

Or install from source:

```bash
git clone https://github.com/opensensa/opensensa.git
cd opensensa
pip install -e .
```

### Create a Project

```bash
opensensa init my-project
cd my-project
```

This scaffolds:

```
my-project/
├── opensensa.yaml        # Model endpoints, server ports, directories
├── .env                  # API keys (gitignored)
├── agents/
│   └── agent-manager.md  # Built-in meta-agent for creating other agents
└── tools/
    ├── add_numbers.py        # Example tools
    ├── csv_formatter.py
    └── generate_visualization.py
```

### Configure Your Model

Edit `opensensa.yaml`:

```yaml
models:
  default: my-model
  registry:
    my-model:
      base_url: https://api.openai.com/v1
      api_key: ${OPENAI_API_KEY}
      model_name: gpt-4.1-mini
```

Set your API key:

```bash
echo "OPENAI_API_KEY=sk-..." >> .env
```

<details>
<summary><strong>Using a local model (Ollama, vLLM, LM Studio)?</strong></summary>

```yaml
models:
  default: local-llama
  registry:
    local-llama:
      base_url: http://localhost:11434/v1   # Ollama
      api_key: none
      model_name: llama3.3
```

No API key needed — just point `base_url` at your local endpoint.

</details>

### Start Chatting

```bash
opensensa chat
```

This starts the MCP + A2A servers in the background, presents an agent picker, and drops you into an interactive Rich terminal session. All agents are live and can call each other over A2A.

### Run as a Service

```bash
opensensa serve
```

Headless mode — starts MCP tool server + A2A agent server. Each agent gets its own endpoint:

```
http://localhost:8000/agents/agent-manager/                    # JSON-RPC endpoint
http://localhost:8000/agents/agent-manager/.well-known/agent-card.json  # Agent Card
http://localhost:8000/agents/                                  # List all agents
```

Any A2A-compliant client can discover and talk to your agents.

## Defining Agents

Each agent is a `.md` file in your `agents/` directory:

```markdown
---
name: clinical-researcher
description: Analyzes clinical trial data and summarizes findings
model: gpt-4.1-mini
tools:
  - csv_formatter
  - generate_visualization
sub_agents:
  - statistician
  - data-analyst
skills:
  - id: trial-analysis
    name: Clinical Trial Analysis
    description: Analyze clinical trial data including endpoints, outcomes, and methodology
    tags: [clinical-trials, data-analysis]
    examples:
      - "Analyze the Phase III trial results for drug X"
input_modes: ["text/plain"]
output_modes: ["text/plain", "application/json"]
---

# Clinical Research Assistant

You are a clinical research analyst. Your job is to help users understand
clinical trial data, outcomes, and study methodology.

## Guidelines
- Always cite source data when making claims
- Use visualizations when presenting comparative data
- For statistical analysis, delegate to the statistician agent
```

**How it works:**
- The `---` YAML frontmatter configures the agent (name, model, tools, delegation targets, A2A skills)
- The markdown body becomes the system prompt sent to the LLM
- Frontmatter is *never* sent to the LLM — only the markdown body
- The agent automatically gets an A2A endpoint with an Agent Card generated from the frontmatter

## Writing Tools

Tools are plain Python files in your `tools/` directory. Any function decorated with `@mcp.tool()` is auto-registered:

```python
# tools/search_papers.py
from fastmcp import FastMCP

mcp = FastMCP()

@mcp.tool()
def search_papers(query: str, max_results: int = 10) -> str:
    """Search the medical literature for relevant papers.
    
    Args:
        query: Search terms or research question
        max_results: Maximum number of results to return
    """
    # Your implementation here
    return f"Found {max_results} papers for: {query}"
```

Or use the `register(mcp)` pattern for tools that need the server instance:

```python
# tools/database_query.py
def register(mcp):
    @mcp.tool()
    def query_database(sql: str) -> str:
        """Execute a read-only SQL query."""
        # ...
        return results
```

Generate a tool skeleton:

```bash
opensensa add-tool my_new_tool
```

## Multi-Agent Delegation

Agents delegate to other agents via the A2A protocol. Declare delegation targets in frontmatter:

```yaml
---
name: project-manager
sub_agents:
  - researcher
  - writer
  - reviewer
---
```

When this agent runs, it can call the `delegate` tool to send tasks to its sub-agents:

```
User: "Write a blog post about transformer architectures"

project-manager → delegate(agent_name="researcher", message="Find key papers on transformer architectures")
  researcher processes and returns findings
project-manager → delegate(agent_name="writer", message="Write a blog post using these findings: ...")
  writer produces draft
project-manager → delegate(agent_name="reviewer", message="Review this draft for accuracy: ...")
  reviewer returns feedback
project-manager synthesizes everything and responds
```

Under the hood, every delegation is a real A2A `SendMessage` JSON-RPC call — the same protocol external agents would use. Delegation depth is capped at 5 hops to prevent infinite loops.

## Framework Tools

OpenSensa includes built-in MCP tools that are always available to agents:

| Tool | Description |
|---|---|
| `delegate` | Delegate a task to a sub-agent by name (auto-enabled when `sub_agents` is declared) |
| `discover_agents` | Fetch A2A Agent Cards from local + remote agents |
| `send_to_agent` | Low-level A2A SendMessage to a specific URL (advanced) |
| `create_agent` | Create a new agent `.md` file |
| `edit_agent` | Modify an existing agent's configuration |
| `delete_agent` | Remove an agent (with confirmation) |
| `list_tools` | List all available MCP tools |

## Configuration Reference

Full `opensensa.yaml` options:

```yaml
models:
  default: my-model                  # Default model for agents that don't specify one
  registry:
    my-model:
      base_url: https://api.openai.com/v1
      api_key: ${OPENAI_API_KEY}     # Environment variable interpolation
      model_name: gpt-4.1-mini
    local-llama:
      base_url: http://localhost:11434/v1
      api_key: none
      model_name: llama3.3

server:
  host: 0.0.0.0
  orchestrator_port: 8000            # A2A agent server
  mcp_port: 8001                     # MCP tool server

agents:
  directory: ./agents/               # Agent .md files

tools:
  directory: ./tools/                # Tool .py files
  builtin: true                      # Include bundled example tools

remote_agents:                       # External A2A agents to discover
  - url: https://researcher.example.com
  - url: http://localhost:9001

logging:
  level: info                        # debug | info | warning | error
  file: ./logs/opensensa.jsonl        # Structured JSON log output
```

## CLI Reference

| Command | Description |
|---|---|
| `opensensa init [dir]` | Scaffold a new project with config, agents, and sample tools |
| `opensensa chat [agent-name]` | Interactive Rich TUI — starts servers, opens a conversation |
| `opensensa serve` | Start MCP + A2A servers in headless mode |
| `opensensa serve --web` | Headless mode with browser-based web UI at `/web` |
| `opensensa add-tool <name>` | Generate a tool skeleton in `tools/` |
| `opensensa add-agent <name>` | Generate an agent skeleton in `agents/` |
| `opensensa list-tools` | List all registered MCP tools |
| `opensensa list-agents` | List all agents (local + remote) |
| `opensensa test` | Smoke test — validates config, agents, and tools |

## Architecture

OpenSensa uses a clean two-protocol architecture:

```
┌─────────────────────────────────────────────────────────┐
│                   OpenSensa Server                       │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  Agent A     │  │  Agent B     │  │  Agent C     │    │
│  │  (A2A)      │  │  (A2A)      │  │  (A2A)      │     │
│  │  /agents/a/ │  │  /agents/b/ │  │  /agents/c/ │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
│         │                │                │              │
│         │     A2A SendMessage (JSON-RPC)  │              │
│         │◄──────────────►│◄──────────────►│              │
│         │                │                │              │
│  ┌──────┴────────────────┴────────────────┴──────┐      │
│  │              MCP Tool Server                   │      │
│  │         (user tools + framework tools)         │      │
│  └────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────┘
         │
         ▼
   Any OpenAI-compatible LLM
   (OpenAI, Ollama, vLLM, Groq, Together, ...)
```

- **Each agent** is its own A2A server with its own URL, Agent Card, executor, and task store
- **MCP** handles tool serving — tools are registered once, available to all agents
- **A2A** handles agent-to-agent communication — `delegate`, `discover_agents`, `send_to_agent` all speak A2A
- **OpenAI Agents SDK** runs the agent loop (prompt → LLM → tool calls → response)

## Interoperability

Because OpenSensa agents are A2A-compliant servers, they interoperate with any A2A-compatible system:

- **Google ADK** agents can discover and call OpenSensa agents via Agent Cards
- **LangGraph**, **CrewAI**, or any A2A client can send `SendMessage` to your agents
- OpenSensa agents can call external A2A agents by adding them to `remote_agents` in config
- Agent Cards are served at the standard `/.well-known/agent-card.json` path

## Web UI

Run `opensensa serve --web` and open `http://localhost:8000/web`:

- **Agent sidebar** — compact cards for all agents, click to start a chat
- **Real-time chat** — streaming responses with tool call animations
- **Delegation tree** — visual tree showing agent-to-agent calls as they happen, including nested delegation chains (A → B → C)
- **Agent CRUD** — create, edit, and delete agents from the browser

## Development

### Prerequisites

- Python 3.10+

### Setup

```bash
git clone https://github.com/opensensa/opensensa.git
cd opensensa
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest
```

### Linting

```bash
ruff check src/ tests/
```

### Project Structure

```
src/opensensa/
├── cli.py                 # Click CLI commands
├── config.py              # YAML config loader + Pydantic validation
├── a2a/                   # A2A protocol layer
│   ├── agent_card.py      # AgentCard builder from frontmatter
│   ├── executor.py        # A2A → OpenAI Agents SDK bridge
│   ├── client.py          # A2A client for outbound requests
│   └── task_store.py      # In-memory task storage
├── orchestrator/          # Server + agent lifecycle
│   ├── server.py          # Per-agent A2A sub-apps on FastAPI
│   ├── agent_builder.py   # Agent construction + MCP wiring
│   ├── agent_registry.py  # Filesystem agent discovery
│   ├── models.py          # OpenAI-compatible model wrapper
│   └── tracing.py         # Structured trace spans
├── mcp_server/            # MCP tool server
│   ├── server.py          # FastMCP server
│   └── tool_loader.py     # Auto-discovery from directory
├── framework_tools/       # Built-in MCP tools
│   ├── delegate.py        # Agent-to-agent delegation
│   ├── discover_agents.py # A2A Agent Card fetching
│   ├── create_agent.py    # Agent CRUD
│   └── ...
├── interactive/           # Rich TUI for `opensensa chat`
│   ├── chat.py            # Chat session + RunHooks
│   ├── ui.py              # Rich components
│   └── call_graph.py      # Live call-graph tree
└── web/                   # Browser UI
    ├── routes.py          # FastAPI routes
    ├── chat_manager.py    # Session management
    ├── static/            # JS + CSS
    └── templates/         # HTML
```

## Roadmap

- [ ] `opensensa deploy` — single-command cloud deployment
- [ ] Persistent task store (SQLite / PostgreSQL)
- [ ] Agent-level authentication and API keys
- [ ] Trace viewer UI
- [ ] Plugin system for custom executors
- [ ] Windows and macOS testing

## Contributing

Contributions are welcome! Please open an issue to discuss what you'd like to change before submitting a PR.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes and add tests
4. Run `pytest` and `ruff check src/ tests/`
5. Submit a pull request

## License

[Apache 2.0](LICENSE) — © 2025 OpenSensa Team
