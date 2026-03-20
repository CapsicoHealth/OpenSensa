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

"""Tracing — structured trace context for agent execution.

Provides AgentTraceContext and AgentSpan for hierarchical tracing of
agent runs, tool calls, and delegations. All output goes to structured
JSON logs (no database).
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from uuid import uuid4

logger = logging.getLogger("opensensa.tracing")


@dataclass
class AgentSpan:
    """A single span in an agent execution trace."""
    span_id: str = field(default_factory=lambda: str(uuid4()))
    parent_span_id: Optional[str] = None
    trace_id: str = ""
    agent_name: str = ""
    event_type: str = "agent_run"  # agent_run, tool_call, delegation, etc.
    start_time_ms: int = 0
    end_time_ms: int = 0
    duration_ms: int = 0
    status: str = "started"  # started, completed, error
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)  # input_tokens, output_tokens

    def complete(self, status: str = "completed", **extra_metadata):
        self.end_time_ms = int(time.time() * 1000)
        self.duration_ms = self.end_time_ms - self.start_time_ms
        self.status = status
        self.metadata.update(extra_metadata)
        self._emit_log()

    def _emit_log(self):
        """Emit structured JSON log for this span."""
        entry = {
            "event": "trace_span",
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "agent_name": self.agent_name,
            "event_type": self.event_type,
            "status": self.status,
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "duration_ms": self.duration_ms,
        }
        if self.usage:
            entry["usage"] = self.usage
        if self.metadata:
            entry["metadata"] = self.metadata

        record = logger.makeRecord(
            name="opensensa.tracing",
            level=logging.INFO,
            fn="",
            lno=0,
            msg=f"Span: {self.agent_name}/{self.event_type} ({self.status}, {self.duration_ms}ms)",
            args=(),
            exc_info=None,
        )
        record.structured_data = entry  # type: ignore[attr-defined]
        logger.handle(record)


class AgentTraceContext:
    """Manages a tree of spans for a single request trace."""

    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or str(uuid4())
        self._spans: list[AgentSpan] = []
        self._active_span: Optional[AgentSpan] = None

    def start_span(
        self,
        agent_name: str,
        event_type: str = "agent_run",
        parent_span_id: Optional[str] = None,
        **metadata,
    ) -> AgentSpan:
        """Create and start a new span."""
        if parent_span_id is None and self._active_span:
            parent_span_id = self._active_span.span_id

        span = AgentSpan(
            trace_id=self.trace_id,
            agent_name=agent_name,
            event_type=event_type,
            parent_span_id=parent_span_id,
            start_time_ms=int(time.time() * 1000),
            metadata=metadata,
        )
        self._spans.append(span)
        self._active_span = span
        return span
