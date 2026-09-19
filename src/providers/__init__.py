"""
Provider registry.

`build_provider` is the only entry point the rest of the action uses; nothing
outside this package imports a specific adapter.
"""

import logging
import os

from config import (
    ANTHROPIC,
    API_KEY_ENV_VARS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODELS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    GEMINI,
    OPENAI,
    OPENAI_COMPATIBLE,
    PROVIDERS,
)
from providers.anthropic_provider import AnthropicProvider
from providers.base import (
    LLMProvider,
    ProviderConfigurationError,
    ProviderError,
    ReviewResult,
    Usage,
)
from providers.gemini_provider import GeminiProvider
from providers.openai_provider import OpenAICompatibleProvider, OpenAIProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[LLMProvider]] = {
    OPENAI: OpenAIProvider,
    ANTHROPIC: AnthropicProvider,
    GEMINI: GeminiProvider,
    OPENAI_COMPATIBLE: OpenAICompatibleProvider,
}

__all__ = [
    "LLMProvider",
    "ProviderConfigurationError",
    "ProviderError",
    "ReviewResult",
    "Usage",
    "build_provider",
]


def build_provider(
    provider: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
) -> LLMProvider:
    """
    Construct the adapter for `provider`.

    Raises ProviderConfigurationError for anything wrong with the configuration
    itself, so the user gets one clear message before any request is billed.
    """
    key = (provider or "").strip().lower()
    if key not in _REGISTRY:
        raise ProviderConfigurationError(
            f"unknown provider `{provider}`. Supported: {', '.join(PROVIDERS)}.",
            provider=str(provider),
            model=str(model),
        )

    resolved_model = model or DEFAULT_MODELS.get(key)
    if not resolved_model:
        raise ProviderConfigurationError(
            f"provider `{key}` has no default model, so `model` is required.",
            provider=key,
            model="",
        )

    resolved_key = api_key or os.getenv(API_KEY_ENV_VARS.get(key, ""), "") or None
    if not resolved_key and key != OPENAI_COMPATIBLE:
        # An OpenAI-compatible server may legitimately need no credential
        # (a local Ollama, for instance), so only the hosted providers insist.
        raise ProviderConfigurationError(
            f"provider `{key}` needs an API key. Pass `api_key`, or set "
            f"{API_KEY_ENV_VARS[key]}.",
            provider=key,
            model=resolved_model,
        )

    logger.info("Using provider %s with model %s", key, resolved_model)
    return _REGISTRY[key](
        resolved_model,
        api_key=resolved_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
