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

"""Structured JSON logging and LoggedMCP wrapper.

Provides:
- setup_logging(): Configures structured JSON logging for the framework
- LoggedMCP: Wrapper around FastMCP that logs every tool call as structured JSON
"""

import asyncio
import functools
import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger("opensensa")


# ---------------------------------------------------------------------------
# Structured JSON formatter
# ---------------------------------------------------------------------------

class StructuredJSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any extra structured data attached to the record
        if hasattr(record, "structured_data"):
            log_entry.update(record.structured_data)
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging(
    level: str = "info",
    log_file: Optional[str] = None,
    *,
    console_output: bool = True,
) -> None:
    """Configure structured logging for OpenSensa.

    Args:
        level: Log level string (debug, info, warning, error).
        log_file: Optional path to a .jsonl file for persistent logs.
        console_output: If False, skip the stderr handler (useful in chat mode
            where Rich owns the terminal).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger("opensensa")
    root.setLevel(log_level)

    # Remove existing handlers to avoid duplicates on reload
    root.handlers.clear()

    # Console handler — only when not in interactive chat mode
    if console_output:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(log_level)
        console.setFormatter(StructuredJSONFormatter())
        root.addHandler(console)

    # Optional file handler
    if log_file:
        from pathlib import Path

        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        fh.setLevel(log_level)
        fh.setFormatter(StructuredJSONFormatter())
        root.addHandler(fh)

    # Don't propagate to root logger
    root.propagate = False


# ---------------------------------------------------------------------------
# Tool call structured log helper
# ---------------------------------------------------------------------------

def _log_tool_call(
    tool_name: str,
    parameters: Optional[dict],
    response: Any,
    status: str,
    start_epoch_ms: int,
    end_epoch_ms: int,
    error: Optional[str] = None,
) -> None:
    """Emit a structured log entry for a tool invocation."""
    entry = {
        "event": "tool_call",
        "tool_name": tool_name,
        "status": status,
        "duration_ms": end_epoch_ms - start_epoch_ms,
        "start_epoch_ms": start_epoch_ms,
        "end_epoch_ms": end_epoch_ms,
    }
    if parameters:
        # Truncate very large parameter values for logging
        entry["parameters"] = _truncate(parameters)
    if error:
        entry["error"] = error
    if status == "success" and response is not None:
        entry["response_preview"] = _truncate(response, max_size=2000)

    tool_logger = logging.getLogger("opensensa.tools")
    record = tool_logger.makeRecord(
        name="opensensa.tools",
        level=logging.INFO if status == "success" else logging.ERROR,
        fn="",
        lno=0,
        msg=f"Tool call: {tool_name} ({status}, {end_epoch_ms - start_epoch_ms}ms)",
        args=(),
        exc_info=None,
    )
    record.structured_data = entry  # type: ignore[attr-defined]
    tool_logger.handle(record)


def _truncate(data: Any, max_size: int = 100_000) -> Any:
    """Truncate data to prevent log explosion."""
    if data is None:
        return None
    try:
        json_str = json.dumps(data, default=str)
        if len(json_str) > max_size:
            return {"_truncated": True, "_size": len(json_str), "_preview": json_str[:1000]}
        return data
    except Exception:
        return {"_error": "Could not serialize"}


# ---------------------------------------------------------------------------
# LoggedMCP wrapper
# ---------------------------------------------------------------------------

def _create_logged_wrapper(func: Callable, tool_name: str) -> Callable:
    """Create a wrapper that emits structured JSON logs for each tool call."""

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        start = int(time.time() * 1000)
        try:
            result = await func(*args, **kwargs)
            end = int(time.time() * 1000)
            _log_tool_call(tool_name, kwargs or None, result, "success", start, end)
            return result
        except Exception as e:
            end = int(time.time() * 1000)
            _log_tool_call(tool_name, kwargs or None, None, "error", start, end, error=str(e))
            raise

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        start = int(time.time() * 1000)
        try:
            result = func(*args, **kwargs)
            end = int(time.time() * 1000)
            _log_tool_call(tool_name, kwargs or None, result, "success", start, end)
            return result
        except Exception as e:
            end = int(time.time() * 1000)
            _log_tool_call(tool_name, kwargs or None, None, "error", start, end, error=str(e))
            raise

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


class LoggedMCP:
    """Wrapper around FastMCP that automatically logs all tool calls as structured JSON.

    Usage:
        from mcp.server.fastmcp import FastMCP
        from opensensa.utils.logging import LoggedMCP

        _mcp = FastMCP("ToolServer", host="0.0.0.0", port=8001)
        mcp = LoggedMCP(_mcp)

        @mcp.tool(title="My Tool", description="...")
        def my_tool(query: str) -> dict:
            return {"result": "..."}
    """

    def __init__(self, mcp_instance: Any, enable_logging: bool = True):
        self._mcp = mcp_instance
        self._enable_logging = enable_logging
        self._registered_tools: dict[str, dict[str, Any]] = {}

    def tool(self, *args: Any, **kwargs: Any) -> Callable:
        """Decorator that registers a tool with automatic structured logging."""
        # Handle tags shorthand → merge into meta
        tags = kwargs.pop("tags", None)
        if tags is not None:
            meta = kwargs.get("meta") or {}
            meta["tags"] = [str(t) for t in tags]
            kwargs["meta"] = meta

        tool_title = kwargs.get("title", None)

        def decorator(func: Callable) -> Callable:
            tool_name = tool_title or func.__name__

            if self._enable_logging:
                logged_func = _create_logged_wrapper(func, tool_name)
            else:
                logged_func = func

            decorated = self._mcp.tool(*args, **kwargs)(logged_func)

            meta = kwargs.get("meta") or {}
            self._registered_tools[tool_name] = {
                "function": func.__name__,
                "title": tool_title,
                "description": kwargs.get("description", ""),
                "logged": self._enable_logging,
                "tags": meta.get("tags", []),
            }
            return decorated

        return decorator

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Proxy to underlying MCP run method."""
        return self._mcp.run(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Proxy all other attributes to the underlying MCP instance."""
        return getattr(self._mcp, name)

    @property
    def registered_tools(self) -> dict[str, dict[str, Any]]:
        """Return dict of all registered tools and their metadata."""
        return self._registered_tools.copy()
