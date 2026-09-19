"""
OpenAI adapter, and the OpenAI-compatible adapter built on top of it.

The compatible variant is the same code pointed at a different base_url, which
is what Ollama, vLLM, Azure OpenAI, OpenRouter, Together and most local servers
expose. That is the whole reason to keep this adapter generic.
"""

import logging

from config import OPENAI, OPENAI_COMPATIBLE
from providers.base import LLMProvider, ProviderConfigurationError, Usage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You are an expert software engineer reviewing a code change."


class OpenAIProvider(LLMProvider):
    name = OPENAI

    def _client(self):
        # Imported lazily so that a broken or missing SDK for a provider the
        # user did not select cannot stop the action from running.
        from openai import OpenAI

        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            # Retries are handled by the base class so that every provider
            # retries the same way and the log says so.
            max_retries=0,
        )

    def _complete(self, prompt: str, schema: dict | None) -> tuple[str, Usage]:
        response = self._client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        text = response.choices[0].message.content or ""
        usage = Usage(
            input_tokens=getattr(response.usage, "prompt_tokens", None),
            output_tokens=getattr(response.usage, "completion_tokens", None),
        )
        return text, usage

    def _describe_failure(self, exc: Exception) -> str:
        status = getattr(exc, "status_code", None)
        if status == 401:
            return (
                "the API key was rejected (401). Check that the secret you pass "
                "to `api_key` is set and has not been revoked."
            )
        if status == 404:
            return (
                f"the model `{self.model}` was not found (404). Check the model "
                "ID against the provider's documentation."
            )
        if status == 429:
            return "the provider rate limited this request (429) and retries did not clear it."
        return super()._describe_failure(exc)


class OpenAICompatibleProvider(OpenAIProvider):
    """Any server that speaks the OpenAI chat completions API."""

    name = OPENAI_COMPATIBLE

    def __init__(self, model: str, **kwargs):
        super().__init__(model, **kwargs)
        if not self.base_url:
            raise ProviderConfigurationError(
                "provider `openai-compatible` requires `base_url` — the address of "
                "the server to talk to, for example http://localhost:11434/v1",
                provider=self.name,
                model=model,
            )
