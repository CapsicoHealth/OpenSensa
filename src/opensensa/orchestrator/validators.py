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

"""Request validation utilities."""

from typing import Any, Optional


class FrameworkError(Exception):
    """Base exception for framework errors."""
    pass


class ValidationError(FrameworkError):
    """Request validation error."""
    def __init__(self, message: str, field: Optional[str] = None):
        self.field = field
        super().__init__(message)


class AgentConfigurationError(FrameworkError):
    """Agent configuration or setup error."""
    pass


class ModelNotFoundError(FrameworkError):
    """Model reference could not be resolved."""
    pass


def validate_agent_name(name: str) -> str:
    """Validate and normalize an agent name."""
    if not name or not name.strip():
        raise ValidationError("Agent name cannot be empty", field="name")
    return name.strip()
