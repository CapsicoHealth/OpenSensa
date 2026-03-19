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

"""Framework tool: send_to_agent — sends A2A SendMessage to a remote agent."""

import json
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("opensensa.framework_tools")

# Maximum delegation depth to prevent infinite loops
MAX_A2A_DEPTH = 5

# Header used to propagate current delegation depth
_DEPTH_HEADER = "X-A2A-Depth"


def register(mcp):
    """Register the send_to_agent tool."""

    @mcp.tool(
        title="Send Message to Agent",
        description=(
            "Send a message to another AI agent via the A2A protocol. Use discover_agents "
            "first to find the right agent and its URL, then use this tool to delegate a task. "
            "Returns the agent's response as an A2A Task with artifacts."
        ),
        tags=["framework", "a2a", "delegation"],
    )
    async def send_to_agent(
        agent_url: str,
        message: str,
        task_id: Optional[str] = None,
        blocking: bool = True,
        current_depth: int = 0,
        client_request_id: Optional[str] = None,
        context_headers: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Send an A2A SendMessage JSON-RPC request to a remote agent.

        Args:
            agent_url: Base URL of the target agent (e.g. http://localhost:9000).
            message: The text message to send to the agent.
            task_id: Optional existing task ID for multi-turn conversations.
            blocking: If True, wait for the task to complete. If False, return immediately.
            current_depth: Current delegation depth (auto-managed by framework).
            client_request_id: Original client JSON-RPC id for session tracking.
            context_headers: Context headers to cascade to the target agent.

        Returns:
            A2A Task response with status and artifacts.
        """
        # Enforce depth limit to prevent infinite delegation loops
        if current_depth >= MAX_A2A_DEPTH:
            logger.warning(
                f"A2A delegation depth limit reached ({current_depth}/{MAX_A2A_DEPTH}). "
                f"Refusing to delegate to {agent_url}."
            )
            return {
                "status": "error",
                "error": (
                    f"Delegation depth limit reached ({MAX_A2A_DEPTH}). "
                    "This prevents infinite agent-to-agent loops. "
                    "Try handling this task directly instead of delegating."
                ),
            }

        url = agent_url.rstrip("/")
        # POST to the agent's root — this is the JSON-RPC endpoint
        # for per-agent sub-apps mounted at /agents/{name}/
        a2a_endpoint = f"{url}/"

        # Build JSON-RPC SendMessage request
        import uuid

        params: dict[str, Any] = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
                "messageId": str(uuid.uuid4()),
            }
        }
        if task_id:
            params["message"]["taskId"] = task_id

        # Cascade context headers to sub-agent via A2A metadata
        if context_headers:
            params.setdefault("metadata", {})["context_headers"] = context_headers

        payload = {
            "jsonrpc": "2.0",
            "id": client_request_id or str(uuid.uuid4()),
            "method": "message/send",
            "params": params,
        }

        # Propagate depth via header so the receiving agent can track it
        next_depth = current_depth + 1
        headers = {
            "Content-Type": "application/json",
            _DEPTH_HEADER: str(next_depth),
        }
        # Propagate the original client request id
        if client_request_id:
            headers["X-A2A-Client-Request-Id"] = client_request_id

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    a2a_endpoint,
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                result = resp.json()

                if "error" in result:
                    return {
                        "status": "error",
                        "error": result["error"],
                    }

                return {
                    "status": "success",
                    "result": result.get("result", {}),
                }

        except httpx.TimeoutException:
            return {"status": "error", "error": f"Request to {a2a_endpoint} timed out"}
        except Exception as e:
            logger.error(f"A2A SendMessage to {a2a_endpoint} failed: {e}")
            return {"status": "error", "error": str(e)}
