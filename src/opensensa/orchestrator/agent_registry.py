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

"""Filesystem-based agent discovery — scans agents/ directory for .md files with YAML frontmatter.

Each .md file becomes an agent definition with:
  - Frontmatter → agent config (name, description, model, tools, skills, etc.)
  - Markdown body → system prompt
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import frontmatter

logger = logging.getLogger("opensensa.agents")


@dataclass
class AgentSkill:
    """An A2A Agent Card skill derived from frontmatter."""
    id: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


def _parse_context_headers(raw: Any) -> list[str]:
    """Normalize context_headers from YAML — accepts a list or a dict (legacy)."""
    if isinstance(raw, list):
        return [str(h) for h in raw]
    if isinstance(raw, dict):
        return list(raw.keys())
    return []


@dataclass
class AgentDefinition:
    """A parsed agent definition from a .md file."""
    name: str
    description: str
    model: str
    tools: list[str]
    sub_agents: list[str]
    system_prompt: str
    skills: list[AgentSkill]
    input_modes: list[str]
    output_modes: list[str]
    context_headers: list[str]
    source_path: Path

    @classmethod
    def from_file(cls, path: Path) -> "AgentDefinition":
        """Parse a frontmatter .md file into an AgentDefinition."""
        post = frontmatter.load(str(path))
        meta = post.metadata

        # Parse skills
        raw_skills = meta.get("skills", [])
        skills = []
        for s in raw_skills:
            if isinstance(s, dict):
                skills.append(AgentSkill(
                    id=s.get("id", ""),
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    tags=s.get("tags", []),
                    examples=s.get("examples", []),
                ))

        # Parse sub_agents — list of agent names this agent can delegate to
        raw_sub_agents = meta.get("sub_agents", [])
        sub_agents = [str(s) for s in raw_sub_agents] if raw_sub_agents else []

        return cls(
            name=meta.get("name", path.stem),
            description=meta.get("description", ""),
            model=meta.get("model", "${default}"),
            tools=meta.get("tools", []),
            sub_agents=sub_agents,
            system_prompt=post.content.strip(),
            skills=skills,
            input_modes=meta.get("input_modes", ["text/plain"]),
            output_modes=meta.get("output_modes", ["text/plain"]),
            context_headers=_parse_context_headers(meta.get("context_headers", [])),
            source_path=path,
        )


class AgentRegistry:
    """Discovers and manages agent definitions from the filesystem.

    Scans the agents directory for .md files, parses them, and provides
    lookup by name. Re-scans on each access to pick up file changes
    without restart.
    """

    def __init__(self, agents_directory: str | Path):
        self._agents_dir = Path(agents_directory).resolve()
        self._cache: dict[str, AgentDefinition] = {}
        self._last_scan_mtimes: dict[str, float] = {}

    @property
    def agents_dir(self) -> Path:
        return self._agents_dir

    def scan(self) -> dict[str, AgentDefinition]:
        """Scan the agents directory and return all agent definitions.

        Re-reads files that have changed since the last scan.
        """
        if not self._agents_dir.exists():
            logger.warning(f"Agents directory does not exist: {self._agents_dir}")
            return {}

        current_files: set[str] = set()

        for md_file in sorted(self._agents_dir.glob("*.md")):
            file_key = str(md_file)
            current_files.add(file_key)

            try:
                mtime = md_file.stat().st_mtime
                # Skip if unchanged
                if file_key in self._last_scan_mtimes and self._last_scan_mtimes[file_key] == mtime:
                    continue

                agent_def = AgentDefinition.from_file(md_file)
                self._cache[agent_def.name] = agent_def
                self._last_scan_mtimes[file_key] = mtime
                logger.info(f"Loaded agent: {agent_def.name} from {md_file.name}")

            except Exception as e:
                logger.error(f"Failed to parse agent file {md_file.name}: {e}")

        # Remove agents whose files were deleted
        to_remove = []
        for file_key in list(self._last_scan_mtimes.keys()):
            if file_key not in current_files:
                to_remove.append(file_key)
        for file_key in to_remove:
            del self._last_scan_mtimes[file_key]
            # Find and remove the agent from cache
            for name, defn in list(self._cache.items()):
                if str(defn.source_path) == file_key:
                    del self._cache[name]
                    logger.info(f"Removed agent: {name} (file deleted)")
                    break

        return self._cache.copy()

    def get(self, name: str) -> Optional[AgentDefinition]:
        """Get an agent definition by name, re-scanning if needed."""
        self.scan()
        return self._cache.get(name)

    def list_agents(self) -> list[AgentDefinition]:
        """Return all known agent definitions."""
        self.scan()
        return list(self._cache.values())

    def agent_names(self) -> list[str]:
        """Return all known agent names."""
        self.scan()
        return list(self._cache.keys())
