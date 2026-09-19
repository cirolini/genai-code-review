"""
Phase 1 acceptance test.

The same fixture diff has to be reviewable by every provider, chosen purely by
configuration, with nothing above the provider layer knowing which one ran.
Each SDK is mocked at its import site, so this needs no key and no network.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from main import create_review_prompt, format_review_comment
from providers import build_provider

FIXTURE = (Path(__file__).parent / "fixtures" / "sample.diff").read_text()
REVIEW_TEXT = "This reintroduces a SQL injection; use a parameterised query."


def _fake_openai_module():
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=REVIEW_TEXT))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
    )
    return SimpleNamespace(OpenAI=MagicMock(return_value=client))


def _fake_anthropic_module():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=REVIEW_TEXT)],
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
    )
    return SimpleNamespace(Anthropic=MagicMock(return_value=client))


def _fake_genai_module():
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(
        text=REVIEW_TEXT,
        usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=20),
    )
    types = SimpleNamespace(GenerateContentConfig=MagicMock())
    # `types` must be an attribute of the module object too, because the
    # adapter does `from google.genai import types`.
    genai = SimpleNamespace(Client=MagicMock(return_value=client), types=types)
    return genai, types


CASES = [
    ("openai", {"api_key": "k"}, "gpt-5.6-luna"),
    ("anthropic", {"api_key": "k"}, "claude-sonnet-5"),
    ("gemini", {"api_key": "k"}, "gemini-3.8-flash"),
    (
        "openai-compatible",
        {"model": "llama3", "base_url": "http://localhost:11434/v1"},
        "llama3",
    ),
]


class ProviderSwitchTests(unittest.TestCase):
    def test_every_provider_reviews_the_same_diff(self):
        prompt = create_review_prompt(FIXTURE, "en", None)
        genai, genai_types = _fake_genai_module()
        modules = {
            "openai": _fake_openai_module(),
            "anthropic": _fake_anthropic_module(),
            "google": SimpleNamespace(genai=genai),
            "google.genai": genai,
            "google.genai.types": genai_types,
        }

        for name, kwargs, expected_model in CASES:
            with self.subTest(provider=name):
                with patch.dict(sys.modules, modules):
                    provider = build_provider(name, **kwargs)
                    result = provider.review(prompt)

                # Same contract regardless of which vendor answered.
                self.assertEqual(result.text, REVIEW_TEXT)
                self.assertEqual(result.provider, name)
                self.assertEqual(result.model, expected_model)
                self.assertEqual(result.usage.input_tokens, 100)
                self.assertEqual(result.usage.output_tokens, 20)
                self.assertGreaterEqual(result.latency_s, 0.0)

                comment = format_review_comment(result)
                self.assertIn(REVIEW_TEXT, comment)
                self.assertIn(name, comment)

    def test_the_diff_reaches_the_model_intact(self):
        prompt = create_review_prompt(FIXTURE, "en", None)
        self.assertIn("SELECT * FROM users", prompt)
        self.assertIn("app/auth.py", prompt)


if __name__ == "__main__":
    unittest.main()
