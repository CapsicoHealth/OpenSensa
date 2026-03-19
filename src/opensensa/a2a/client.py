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

"""A2A client — sends SendMessage to remote agents.

Used by the send_to_agent framework tool. Supports both raw httpx calls
and (when available) the a2a-sdk client for richer type-safety.
"""

import logging
import uuid
from typing import Any, Optional

import httpx

from a2a.types import (
    AgentCard,
    Message,
    MessageSendParams,
    Role,
    SendMessageRequest,
    TextPart,
)

logger = logging.getLogger("opensensa.a2a")


async def fetch_agent_card(agent_url: str) -> AgentCard:
    """Fetch an A2A Agent Card from a remote agent's well-known URL.

    Args:
        agent_url: Base URL of the agent (e.g. http://localhost:9000).

    Returns:
        The Agent Card as an a2a-sdk AgentCard model.
    """
    url = f"{agent_url.rstrip('/')}/.well-known/agent-card.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return AgentCard.model_validate(resp.json())


async def fetch_agent_card_dict(agent_url: str) -> dict[str, Any]:
    """Fetch an A2A Agent Card as a raw dict (for framework tools).

    Args:
        agent_url: Base URL of the agent.

    Returns:
        The Agent Card as a dict.
    """
    url = f"{agent_url.rstrip('/')}/.well-known/agent-card.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def send_message(
    agent_url: str,
    message: str,
    task_id: Optional[str] = None,
    context_id: Optional[str] = None,
    timeout: float = 120.0,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Send an A2A SendMessage JSON-RPC request to a remote agent.

    Args:
        agent_url: Base URL of the agent.
        message: Text message to send.
        task_id: Optional task ID for multi-turn.
        context_id: Optional context ID for conversation threading.
        timeout: Request timeout in seconds.
        metadata: Optional metadata to include in the request.

    Returns:
        JSON-RPC result dict.
    """
    # POST to the agent's root — the JSON-RPC endpoint for per-agent sub-apps
    url = f"{agent_url.rstrip('/')}/"

    msg_id = str(uuid.uuid4())
    a2a_message: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": message}],
        "messageId": msg_id,
    }
    if task_id:
        a2a_message["taskId"] = task_id
    if context_id:
        a2a_message["contextId"] = context_id

    params: dict[str, Any] = {"message": a2a_message}
    if metadata:
        params["metadata"] = metadata

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": params,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        return resp.json()
