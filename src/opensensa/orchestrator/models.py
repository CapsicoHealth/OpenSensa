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

"""Simplified model layer.

Every model goes through AsyncOpenAI(base_url=..., api_key=...) → either
OpenAIResponsesModel (for OpenAI's own API) or OpenAIChatCompletionsModel
(for everything else — Ollama, vLLM, LM Studio, Together, Groq, Fireworks,
Google — anything with an OpenAI-compatible /chat/completions endpoint).

OpenAI's newer reasoning models (e.g. gpt-5.x) reject the combination of
``reasoning_effort`` + function tools on ``/v1/chat/completions`` — they
require ``/v1/responses`` for that. Since the OpenAI Agents SDK defaults
``model_settings.reasoning`` for gpt-5-family models, calling OpenAI's API
must go through OpenAIResponsesModel to avoid a 400 error.
"""

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

from openai import AsyncOpenAI

from opensensa.config import AppConfig, ModelConfig, resolve_model

logger = logging.getLogger("opensensa.orchestrator")

# Hosts that must use the Responses API rather than Chat Completions.
_RESPONSES_API_HOSTS = {"api.openai.com"}


def _requires_responses_api(base_url: str) -> bool:
    try:
        return urlparse(base_url).hostname in _RESPONSES_API_HOSTS
    except ValueError:
        return False


def create_model(model_config: ModelConfig) -> Any:
    """Create a Model instance from a ModelConfig.

    Uses OpenAIResponsesModel for OpenAI's own API (required for gpt-5-family
    reasoning models combined with function tools) and
    OpenAIChatCompletionsModel for every other OpenAI-compatible endpoint.

    Args:
        model_config: Resolved model configuration with base_url, api_key, model_name.

    Returns:
        A Model instance ready for use with Agent().
    """
    from agents import OpenAIChatCompletionsModel, OpenAIResponsesModel

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

    if _requires_responses_api(model_config.base_url):
        model = OpenAIResponsesModel(
            model=model_config.model_name,
            openai_client=client,
        )
    else:
        model = OpenAIChatCompletionsModel(
            model=model_config.model_name,
            openai_client=client,
        )

    logger.info(
        f"Created model: {model_config.model_name} "
        f"via {model_config.base_url} ({type(model).__name__})"
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
