"""
Tests for the provider layer.

Every provider is exercised through a mocked SDK client, so the suite needs no
API key and makes no network call. What is being tested is the contract each
adapter has to honour: return the text, report the tokens, and turn a failure
into a ProviderError with a message a human can act on.
"""

import copy
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import config
from findings import FINDINGS_SCHEMA, SEVERITIES
from providers import ProviderConfigurationError, ProviderError, build_provider
from providers.anthropic_provider import AnthropicProvider
from providers.base import LLMProvider, Usage, _looks_transient
from providers.gemini_provider import GeminiProvider, to_gemini_schema
from providers.openai_provider import (
    OpenAICompatibleProvider,
    OpenAIProvider,
    to_strict_schema,
)
from providers.retry import RetryPolicy

NO_DELAY = RetryPolicy(attempts=3, base_delay=0.0, max_delay=0.0)


class StatusError(Exception):
    """Stands in for an SDK error that carries an HTTP status code."""

    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class BuildProviderTests(unittest.TestCase):
    def test_defaults_to_the_configured_model_per_provider(self):
        for name, expected in config.DEFAULT_MODELS.items():
            if expected is None:
                continue
            with self.subTest(provider=name):
                provider = build_provider(name, api_key="k")
                self.assertEqual(provider.model, expected)
                self.assertEqual(provider.name, name)

    def test_explicit_model_wins_over_the_default(self):
        provider = build_provider("openai", model="some-other-model", api_key="k")
        self.assertEqual(provider.model, "some-other-model")

    def test_provider_name_is_case_and_space_insensitive(self):
        self.assertIsInstance(build_provider("  OpenAI ", api_key="k"), OpenAIProvider)

    def test_unknown_provider_is_rejected_with_the_supported_list(self):
        with self.assertRaises(ProviderConfigurationError) as ctx:
            build_provider("bedrock", api_key="k")
        self.assertIn("unknown provider", str(ctx.exception))
        self.assertIn("anthropic", str(ctx.exception))

    def test_missing_api_key_is_rejected_before_any_request(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ProviderConfigurationError) as ctx:
                build_provider("anthropic")
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_api_key_falls_back_to_the_provider_env_var(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "from-env"}, clear=True):
            provider = build_provider("gemini")
        self.assertEqual(provider.api_key, "from-env")

    def test_openai_compatible_requires_a_base_url(self):
        with self.assertRaises(ProviderConfigurationError) as ctx:
            build_provider("openai-compatible", model="llama3", api_key="k")
        self.assertIn("base_url", str(ctx.exception))

    def test_openai_compatible_needs_no_key(self):
        """A local Ollama has no credential; requiring one would block it."""
        with patch.dict("os.environ", {}, clear=True):
            provider = build_provider(
                "openai-compatible", model="llama3", base_url="http://localhost:11434/v1"
            )
        self.assertIsInstance(provider, OpenAICompatibleProvider)

    def test_openai_compatible_has_no_default_model(self):
        with self.assertRaises(ProviderConfigurationError) as ctx:
            build_provider("openai-compatible", base_url="http://x/v1", api_key="k")
        self.assertIn("`model` is required", str(ctx.exception))


class OpenAIAdapterTests(unittest.TestCase):
    def _client(self, text="a review", prompt_tokens=11, completion_tokens=7):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
            usage=SimpleNamespace(
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
            ),
        )
        return client

    def test_returns_text_usage_and_latency(self):
        provider = OpenAIProvider("gpt-test", api_key="k")
        with patch.object(provider, "_client", return_value=self._client()):
            result = provider.review("prompt")

        self.assertEqual(result.text, "a review")
        self.assertEqual(result.usage.input_tokens, 11)
        self.assertEqual(result.usage.output_tokens, 7)
        self.assertEqual(result.usage.total_tokens, 18)
        self.assertEqual(result.provider, "openai")
        self.assertEqual(result.model, "gpt-test")
        self.assertGreaterEqual(result.latency_s, 0.0)

    def test_sends_the_configured_sampling_parameters(self):
        provider = OpenAIProvider("gpt-test", api_key="k", temperature=0.2, max_tokens=99)
        client = self._client()
        with patch.object(provider, "_client", return_value=client):
            provider.review("prompt")

        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-test")
        self.assertEqual(kwargs["temperature"], 0.2)
        self.assertEqual(kwargs["max_tokens"], 99)
        self.assertEqual(kwargs["messages"][1]["content"], "prompt")

    def test_empty_content_becomes_an_empty_string_not_none(self):
        provider = OpenAIProvider("gpt-test", api_key="k")
        with patch.object(provider, "_client", return_value=self._client(text=None)):
            self.assertEqual(provider.review("prompt").text, "")

    def test_base_url_is_passed_to_the_sdk(self):
        provider = OpenAICompatibleProvider(
            "llama3", base_url="http://localhost:11434/v1", api_key="k"
        )
        fake_openai = MagicMock()
        with patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=fake_openai)}):
            provider._client()
        self.assertEqual(
            fake_openai.call_args.kwargs["base_url"], "http://localhost:11434/v1"
        )

    def test_auth_failure_explains_itself_without_leaking_the_key(self):
        provider = OpenAIProvider("gpt-test", api_key="super-secret", retry_policy=NO_DELAY)
        client = MagicMock()
        client.chat.completions.create.side_effect = StatusError(401)

        with patch.object(provider, "_client", return_value=client):
            with self.assertRaises(ProviderError) as ctx:
                provider.review("prompt")

        message = str(ctx.exception)
        self.assertIn("401", message)
        self.assertNotIn("super-secret", message)
        self.assertEqual(ctx.exception.provider, "openai")

    def test_unknown_model_is_reported_as_such(self):
        provider = OpenAIProvider("no-such-model", api_key="k", retry_policy=NO_DELAY)
        client = MagicMock()
        client.chat.completions.create.side_effect = StatusError(404)
        with patch.object(provider, "_client", return_value=client):
            with self.assertRaises(ProviderError) as ctx:
                provider.review("prompt")
        self.assertIn("no-such-model", str(ctx.exception))


class AnthropicAdapterTests(unittest.TestCase):
    def test_joins_text_blocks_and_reports_usage(self):
        provider = AnthropicProvider("claude-test", api_key="k")
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="ignored"),
                SimpleNamespace(type="text", text="first "),
                SimpleNamespace(type="text", text="second"),
            ],
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
        )
        with patch.object(provider, "_client", return_value=client):
            result = provider.review("prompt")

        self.assertEqual(result.text, "first second")
        self.assertEqual(result.usage.input_tokens, 5)
        self.assertEqual(result.provider, "anthropic")


class GeminiAdapterTests(unittest.TestCase):
    def test_returns_text_and_maps_usage_metadata(self):
        provider = GeminiProvider("gemini-test", api_key="k")
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="gemini review",
            usage_metadata=SimpleNamespace(
                prompt_token_count=21, candidates_token_count=4
            ),
        )
        with patch.object(provider, "_client", return_value=client):
            result = provider.review("prompt")

        self.assertEqual(result.text, "gemini review")
        self.assertEqual(result.usage.input_tokens, 21)
        self.assertEqual(result.usage.output_tokens, 4)

    def test_invalid_key_message_is_translated(self):
        provider = GeminiProvider("gemini-test", api_key="k", retry_policy=NO_DELAY)
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("API_KEY_INVALID")
        with patch.object(provider, "_client", return_value=client):
            with self.assertRaises(ProviderError) as ctx:
                provider.review("prompt")
        self.assertIn("API key was rejected", str(ctx.exception))


class SchemaAdaptationTests(unittest.TestCase):
    """
    The providers genuinely disagree about JSON Schema, so the canonical schema
    stays provider-neutral and each adapter transforms it. Both of these were
    written after a live request rejected the untransformed schema.
    """

    def test_strict_mode_requires_every_property_to_be_required(self):
        """
        OpenAI strict mode rejects optional properties outright:
        "`required` is required to be supplied and to be an array including
        every key in properties".
        """
        strict = to_strict_schema(FINDINGS_SCHEMA)
        item = strict["properties"]["findings"]["items"]
        self.assertEqual(set(item["required"]), set(item["properties"]))
        self.assertIn("suggestion", item["required"])

    def test_an_optional_property_becomes_nullable_rather_than_mandatory(self):
        """Optionality has to be expressed in the type, not by omission."""
        item = to_strict_schema(FINDINGS_SCHEMA)["properties"]["findings"]["items"]
        self.assertEqual(item["properties"]["suggestion"]["type"], ["string", "null"])
        # A genuinely required field keeps its plain type.
        self.assertEqual(item["properties"]["file"]["type"], "string")

    def test_strict_mode_sets_additional_properties_false(self):
        strict = to_strict_schema(FINDINGS_SCHEMA)
        self.assertIs(strict["additionalProperties"], False)
        self.assertIs(strict["properties"]["findings"]["items"]["additionalProperties"], False)

    def test_gemini_rejects_additional_properties_so_it_is_stripped(self):
        """Gemini returns 400 INVALID_ARGUMENT on `additionalProperties`."""
        cleaned = to_gemini_schema(FINDINGS_SCHEMA)
        self.assertNotIn("additionalProperties", cleaned)
        self.assertNotIn(
            "additionalProperties", cleaned["properties"]["findings"]["items"]
        )

    def test_gemini_schema_keeps_what_the_model_actually_needs(self):
        item = to_gemini_schema(FINDINGS_SCHEMA)["properties"]["findings"]["items"]
        self.assertEqual(item["type"], "object")
        self.assertIn("severity", item["properties"])
        self.assertEqual(item["properties"]["severity"]["enum"], list(SEVERITIES))
        self.assertIn("file", item["required"])

    def test_neither_transform_mutates_the_canonical_schema(self):
        before = copy.deepcopy(FINDINGS_SCHEMA)
        to_strict_schema(FINDINGS_SCHEMA)
        to_gemini_schema(FINDINGS_SCHEMA)
        self.assertEqual(FINDINGS_SCHEMA, before)


class RetryBehaviourTests(unittest.TestCase):
    """The base class owns retries, so it is tested once rather than per adapter."""

    class FlakyProvider(LLMProvider):
        name = "flaky"

        def __init__(self, failures, error, **kwargs):
            super().__init__("m", api_key="k", retry_policy=NO_DELAY, **kwargs)
            self.remaining_failures = failures
            self.error = error
            self.calls = 0

        def _complete(self, prompt, schema):
            self.calls += 1
            if self.remaining_failures > 0:
                self.remaining_failures -= 1
                raise self.error
            return "ok", Usage(1, 1)

    def test_a_transient_failure_is_retried_and_then_succeeds(self):
        provider = self.FlakyProvider(2, StatusError(429))
        result = provider.review("prompt")
        self.assertEqual(result.text, "ok")
        self.assertEqual(provider.calls, 3)
        self.assertEqual(result.attempts, 3)

    def test_retries_are_bounded(self):
        provider = self.FlakyProvider(99, StatusError(503))
        with self.assertRaises(ProviderError):
            provider.review("prompt")
        self.assertEqual(provider.calls, NO_DELAY.attempts)

    def test_a_permanent_failure_is_not_retried(self):
        """Retrying a rejected key wastes the run and delays the real message."""
        provider = self.FlakyProvider(99, StatusError(401))
        with self.assertRaises(ProviderError):
            provider.review("prompt")
        self.assertEqual(provider.calls, 1)


class TransientClassificationTests(unittest.TestCase):
    def test_status_codes(self):
        for status, expected in [
            (429, True), (500, True), (503, True), (408, True),
            (400, False), (401, False), (404, False),
        ]:
            with self.subTest(status=status):
                self.assertIs(_looks_transient(StatusError(status)), expected)

    def test_falls_back_to_the_exception_name(self):
        self.assertTrue(_looks_transient(TimeoutError("slow")))
        self.assertTrue(_looks_transient(ConnectionError("dropped")))
        self.assertFalse(_looks_transient(ValueError("nonsense")))


if __name__ == "__main__":
    unittest.main()


class DefaultResponseCapTests(unittest.TestCase):
    """
    The default `max_tokens` has to hold a full-sized review.

    This is not a taste setting. Structured output is all-or-nothing: if the
    response is cut off mid-JSON, the provider rejects the entire generation
    and the pull request gets no review at all — with a 400 that says "Please
    adjust your prompt" and points nowhere near the cause.

    Measured on a 15-file pull request with ten seeded defects: 2048 returned
    a 400 and nothing else, 8192 returned 11 findings in 3426 output tokens.
    A review that fills the default comment budget needs roughly 350 output
    tokens per finding, so anything under ~4000 puts the failure back within
    reach of an ordinary pull request.
    """

    def test_the_default_holds_a_review_that_fills_the_comment_budget(self):
        self.assertGreaterEqual(config.DEFAULT_MAX_TOKENS, 4096)

    def test_a_provider_built_without_one_gets_the_default(self):
        provider = build_provider("openai", api_key="k")
        self.assertEqual(provider.max_tokens, config.DEFAULT_MAX_TOKENS)

    def test_an_explicit_value_still_wins(self):
        """Lowering it is a supported choice; inheriting a broken one is not."""
        provider = build_provider("openai", api_key="k", max_tokens=512)
        self.assertEqual(provider.max_tokens, 512)
