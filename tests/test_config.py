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

"""Tests for config loading and validation."""

import os
import tempfile
from pathlib import Path

import pytest

from opensensa.config import OpenSensaConfig, load_config, resolve_model


def test_default_config():
    """Loading with no file should return valid defaults."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config(project_dir=tmpdir)
        assert isinstance(config, OpenSensaConfig)
        assert config.server.mcp_port == 8001
        assert config.server.orchestrator_port == 8000


def test_load_config_from_yaml():
    """Load a YAML config file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_yaml = Path(tmpdir) / "opensensa.yaml"
        config_yaml.write_text("""
models:
  default: test-model
  registry:
    test-model:
      base_url: http://localhost:1234/v1
      api_key: test-key
      model_name: test-gpt
server:
  host: 127.0.0.1
  orchestrator_port: 9999
  mcp_port: 9998
""")
        config = load_config(config_path=config_yaml)
        assert config.models.default == "test-model"
        assert config.server.orchestrator_port == 9999
        assert config.models.registry["test-model"].model_name == "test-gpt"


def test_env_var_interpolation():
    """Environment variables in ${VAR} syntax should be resolved."""
    os.environ["_OPENSENSA_TEST_KEY"] = "my-secret-key"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_yaml = Path(tmpdir) / "opensensa.yaml"
            config_yaml.write_text("""
models:
  default: m
  registry:
    m:
      base_url: http://localhost/v1
      api_key: ${_OPENSENSA_TEST_KEY}
      model_name: gpt-test
""")
            config = load_config(config_path=config_yaml)
            assert config.models.registry["m"].api_key == "my-secret-key"
    finally:
        del os.environ["_OPENSENSA_TEST_KEY"]


def test_resolve_model():
    """resolve_model should look up models by name and handle 'default'."""
    config = OpenSensaConfig.model_validate({
        "models": {
            "default": "my-model",
            "registry": {
                "my-model": {
                    "base_url": "http://localhost/v1",
                    "api_key": "key",
                    "model_name": "gpt-4",
                }
            }
        }
    })
    m = resolve_model(config, "default")
    assert m.model_name == "gpt-4"

    m2 = resolve_model(config, "my-model")
    assert m2.model_name == "gpt-4"

    with pytest.raises(ValueError, match="not found"):
        resolve_model(config, "nonexistent")
