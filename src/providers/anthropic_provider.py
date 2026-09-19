"""Anthropic adapter."""

import logging

from config import ANTHROPIC
from providers.base import LLMProvider, Usage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You are an expert software engineer reviewing a code change."


class AnthropicProvider(LLMProvider):
    name = ANTHROPIC

    def _client(self):
        from anthropic import Anthropic

        return Anthropic(
            api_key=self.api_key,
            base_url=self.base_url or None,
            timeout=self.timeout,
            max_retries=0,
        )

    def _complete(self, prompt: str, schema: dict | None) -> tuple[str, Usage]:
        kwargs = {}
        if schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": schema}
            }

        client = self._client()
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        # content is a list of blocks; only the text ones matter here.
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        usage = Usage(
            input_tokens=getattr(response.usage, "input_tokens", None),
            output_tokens=getattr(response.usage, "output_tokens", None),
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
                "ID against Anthropic's documentation."
            )
        if status == 429:
            return "the provider rate limited this request (429) and retries did not clear it."
        return super()._describe_failure(exc)
