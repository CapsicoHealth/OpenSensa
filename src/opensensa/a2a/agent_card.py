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

"""AgentCard builder — creates A2A Agent Cards from agent .md frontmatter.

Uses the a2a-sdk AgentCard Pydantic model for type-safe card construction.
Each agent gets its own AgentCard with a unique URL (per A2A spec).
"""

from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill as A2ASkill,
)

from opensensa.orchestrator.agent_registry import AgentDefinition


def build_agent_card(agent: AgentDefinition, base_url: str) -> AgentCard:
    """Build an A2A AgentCard for a single agent.

    The card's ``url`` is set to ``{base_url}/agents/{agent.name}`` so that
    the agent's JSON-RPC endpoint lives at its own sub-app path.

    Args:
        agent: Parsed agent definition from a .md file.
        base_url: The server base URL (e.g. http://localhost:8000).

    Returns:
        A2A AgentCard (Pydantic model from a2a-sdk).
    """
    skills = []
    for s in agent.skills:
        skill = A2ASkill(
            id=s.id,
            name=s.name,
            description=s.description,
            tags=s.tags or [],
            examples=s.examples if s.examples else None,
        )
        skills.append(skill)

    # If no skills defined, create a default one from the agent itself
    if not skills:
        skills.append(A2ASkill(
            id=agent.name,
            name=agent.name,
            description=agent.description,
            tags=[],
        ))

    return AgentCard(
        name=agent.name,
        description=agent.description,
        url=f"{base_url.rstrip('/')}/agents/{agent.name}",
        version="1.0.0",
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=False,
            state_transition_history=False,
        ),
        default_input_modes=agent.input_modes,
        default_output_modes=agent.output_modes,
        skills=skills,
    )
