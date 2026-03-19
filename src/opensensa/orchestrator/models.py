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

"""Simplified model layer — OpenAIChatCompletionsModel only.

Every model goes through AsyncOpenAI(base_url=..., api_key=...) →
OpenAIChatCompletionsModel. Works with OpenAI, Ollama, vLLM, LM Studio,
Together, Groq, Fireworks — anything with an OpenAI-compatible endpoint.
"""

import logging
import os
import re
from typing import Any

from openai import AsyncOpenAI

from opensensa.config import AppConfig, ModelConfig, resolve_model

logger = logging.getLogger("opensensa.orchestrator")


def create_model(model_config: ModelConfig) -> Any:
    """Create an OpenAIChatCompletionsModel from a ModelConfig.

    Args:
        model_config: Resolved model configuration with base_url, api_key, model_name.

    Returns:
        An OpenAIChatCompletionsModel instance ready for use with Agent().
    """
    from agents import OpenAIChatCompletionsModel

    api_key = model_config.api_key or ""

    # Safety: resolve any leftover ${VAR} references at runtime
    _env_re = re.compile(r"\$\{(\w+)\}")
    match = _env_re.search(api_key)
    if match:
        var_name = match.group(1)
        resolved = os.environ.get(var_name)
        if resolved:
            api_key = _env_re.sub(resolved, api_key)
        else:
            raise ValueError(
                f"API key references ${{{var_name}}} but it is not set in the environment. "
                f"Set it in your .env file or export it in your shell."
            )

    if not api_key or api_key in ("none", "None"):
        api_key = "no-key"  # Some local servers need a non-empty key

    client = AsyncOpenAI(
        base_url=model_config.base_url,
        api_key=api_key,
    )

    model = OpenAIChatCompletionsModel(
        model=model_config.model_name,
        openai_client=client,
    )

    logger.info(
        f"Created model: {model_config.model_name} "
        f"via {model_config.base_url}"
    )
    return model


def create_model_from_ref(config: AppConfig, model_ref: str) -> Any:
    """Resolve a model reference and create the model.

    Args:
        config: Full framework configuration.
        model_ref: Model name or "${default}".

    Returns:
        An OpenAIChatCompletionsModel instance.
    """
    model_config = resolve_model(config, model_ref)
    return create_model(model_config)
