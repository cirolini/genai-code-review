"""Google Gemini adapter."""

import logging

from config import GEMINI
from providers.base import LLMProvider, Usage

logger = logging.getLogger(__name__)

# Gemini accepts only a subset of JSON Schema, and rejects the request outright
# on anything else. `additionalProperties` is the important one: OpenAI's strict
# mode *requires* it, and Gemini returns 400 INVALID_ARGUMENT for it, so one
# schema cannot be sent to both providers unchanged.
GEMINI_SCHEMA_KEYS = frozenset(
    {
        "type",
        "format",
        "description",
        "nullable",
        "enum",
        "items",
        "properties",
        "required",
        "minItems",
        "maxItems",
        "propertyOrdering",
    }
)


def to_gemini_schema(schema):
    """Strip the JSON Schema keywords Gemini does not accept, recursively."""
    if isinstance(schema, list):
        return [to_gemini_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    cleaned = {}
    for key, value in schema.items():
        if key not in GEMINI_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {name: to_gemini_schema(sub) for name, sub in value.items()}
        elif key == "items":
            cleaned[key] = to_gemini_schema(value)
        else:
            cleaned[key] = value
    return cleaned


SYSTEM_PROMPT = "You are an expert software engineer reviewing a code change."


class GeminiProvider(LLMProvider):
    name = GEMINI

    def _client(self):
        from google import genai

        return genai.Client(api_key=self.api_key)

    def _complete(self, prompt: str, schema: dict | None) -> tuple[str, Usage]:
        from google.genai import types

        config_kwargs = {
            "system_instruction": SYSTEM_PROMPT,
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
        }
        if schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = to_gemini_schema(schema)

        # Bind the client to a local name. `self._client().models...` lets the
        # Client be garbage collected as soon as `.models` is resolved, and its
        # teardown closes the transport — the request then fails with "Cannot
        # send a request, as the client has been closed".
        client = self._client()
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        metadata = getattr(response, "usage_metadata", None)
        usage = Usage(
            input_tokens=getattr(metadata, "prompt_token_count", None),
            output_tokens=getattr(metadata, "candidates_token_count", None),
        )
        return response.text or "", usage

    def _describe_failure(self, exc: Exception) -> str:
        message = str(exc)
        if "API_KEY_INVALID" in message or "API key not valid" in message:
            return (
                "the API key was rejected. Check that the secret you pass to "
                "`api_key` is set and has not been revoked."
            )
        if "NOT_FOUND" in message or "not found" in message.lower():
            return (
                f"the model `{self.model}` was not found. Check the model ID "
                "against Google's documentation."
            )
        return super()._describe_failure(exc)
