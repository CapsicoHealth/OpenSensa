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

"""YAML config loader with Pydantic validation and env var interpolation."""

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Pydantic models for opensensa.yaml
# ---------------------------------------------------------------------------

class ModelConfig(BaseModel):
    """A single model entry in the registry."""
    base_url: str
    api_key: str = "none"
    model_name: str

class ModelsConfig(BaseModel):
    """Top-level models section."""
    default: str = "default"
    registry: dict[str, ModelConfig] = Field(default_factory=dict)

class ServerConfig(BaseModel):
    """Server host/port settings."""
    host: str = "0.0.0.0"
    orchestrator_port: int = 8000
    mcp_port: int = 8001

class AgentsConfig(BaseModel):
    """Agents directory settings."""
    directory: str = "./agents/"

class ToolsConfig(BaseModel):
    """Tools directory settings."""
    directory: str = "./tools/"
    builtin: bool = True

class RemoteAgentConfig(BaseModel):
    """A single remote A2A agent."""
    url: str

class LoggingConfig(BaseModel):
    """Logging settings."""
    level: str = "info"
    file: Optional[str] = "./logs/opensensa.jsonl"

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        allowed = {"debug", "info", "warning", "error", "critical"}
        if v.lower() not in allowed:
            raise ValueError(f"logging.level must be one of {allowed}, got '{v}'")
        return v.lower()

class AppConfig(BaseModel):
    """Root configuration model for the framework YAML config file."""
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    remote_agents: list[RemoteAgentConfig] = Field(default_factory=list)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Environment variable interpolation
# ---------------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _interpolate_env(value: Any) -> Any:
    """Recursively interpolate ${VAR} and ${VAR:default} in strings."""
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2)
            env_val = os.environ.get(var_name)
            if env_val is not None:
                return env_val
            if default is not None:
                return default
            return match.group(0)  # Leave as-is if not found and no default
        return _ENV_VAR_RE.sub(_replace, value)
    elif isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_interpolate_env(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: Optional[str | Path] = None, project_dir: Optional[str | Path] = None) -> AppConfig:
    """Load and validate the framework YAML configuration.

    Args:
        config_path: Explicit path to a YAML config file. If None, searches
                     for opensensa.yaml in project_dir, then cwd.
        project_dir: Project root to resolve relative paths against. Defaults to cwd.

    Returns:
        Validated AppConfig instance.
    """
    project_dir = Path(project_dir) if project_dir else Path.cwd()

    # Locate config file
    if config_path:
        config_file = Path(config_path)
    else:
        config_file = project_dir / "opensensa.yaml"
        if not config_file.exists():
            config_file = project_dir / "opensensa.yml"

    # Load YAML
    if config_file.exists():
        with open(config_file) as f:
            raw = yaml.safe_load(f) or {}
    else:
        raw = {}

    # Interpolate env vars
    raw = _interpolate_env(raw)

    # Validate with Pydantic
    config = AppConfig.model_validate(raw)

    return config


def resolve_model(config: AppConfig, model_ref: str) -> ModelConfig:
    """Resolve a model reference to its ModelConfig.

    Handles:
      - "${default}" or "default" → looks up config.models.default
      - Exact name in registry
    """
    if model_ref in ("${default}", "default"):
        model_ref = config.models.default

    if model_ref not in config.models.registry:
        available = list(config.models.registry.keys())
        raise ValueError(
            f"Model '{model_ref}' not found in registry. Available: {available}"
        )

    return config.models.registry[model_ref]
