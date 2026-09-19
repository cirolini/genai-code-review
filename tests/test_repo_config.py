"""
Tests for `.genai-review.yml`.

A repository config file is repository content, so it is untrusted in the same
way the diff is. What matters here is that it cannot do anything a workflow
author would not expect: no credentials, no unknown keys, no failing somebody's
pull request because the YAML is malformed.
"""

import tempfile
import unittest
from pathlib import Path

from repo_config import load, resolve


def write_config(text):
    path = Path(tempfile.mkdtemp()) / ".genai-review.yml"
    path.write_text(text)
    return str(path)


class LoadingTests(unittest.TestCase):
    def test_reads_known_keys_with_the_right_types(self):
        config = load(write_config(
            "provider: anthropic\nmax_comments: 3\nmin_confidence: 0.6\nincremental: false\n"
        ))
        self.assertEqual(config["provider"], "anthropic")
        self.assertEqual(config["max_comments"], 3)
        self.assertEqual(config["min_confidence"], 0.6)
        self.assertIs(config["incremental"], False)

    def test_reads_a_list_key(self):
        config = load(write_config("ignore_paths:\n  - docs/**\n  - '*.md'\n"))
        self.assertEqual(config["ignore_paths"], ["docs/**", "*.md"])

    def test_accepts_a_comma_separated_string_for_a_list_key(self):
        self.assertEqual(load(write_config("panel: openai, anthropic\n"))["panel"],
                         ["openai", "anthropic"])

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual(load("/nonexistent/.genai-review.yml"), {})

    def test_an_empty_file_is_not_an_error(self):
        self.assertEqual(load(write_config("")), {})

    def test_malformed_yaml_is_ignored_rather_than_raised(self):
        """A broken config file must not fail somebody's pull request."""
        self.assertEqual(load(write_config("provider: [unclosed\n")), {})

    def test_a_non_mapping_file_is_ignored(self):
        self.assertEqual(load(write_config("- just\n- a\n- list\n")), {})

    def test_a_wrongly_typed_value_is_dropped_not_coerced_into_nonsense(self):
        config = load(write_config("max_comments: not-a-number\nprovider: openai\n"))
        self.assertNotIn("max_comments", config)
        self.assertEqual(config["provider"], "openai")

    def test_unknown_keys_are_ignored(self):
        config = load(write_config("provider: openai\nmagic_setting: 42\n"))
        self.assertEqual(set(config), {"provider"})


class CredentialTests(unittest.TestCase):
    """A key in a repository file is a key that gets committed by accident."""

    def test_api_keys_are_never_read_from_the_config_file(self):
        for key in ("api_key", "openai_api_key", "github_token", "token"):
            with self.subTest(key=key):
                config = load(write_config(f"{key}: secret-value\nprovider: openai\n"))
                self.assertNotIn(key, config)
                self.assertNotIn("secret-value", str(config))


class PrecedenceTests(unittest.TestCase):
    def test_the_action_input_beats_the_config_file(self):
        """A workflow is the more specific statement of intent."""
        self.assertEqual(resolve("openai", {"provider": "anthropic"}, "provider"), "openai")

    def test_the_config_file_beats_the_default(self):
        self.assertEqual(resolve("", {"provider": "anthropic"}, "provider", "openai"), "anthropic")

    def test_the_default_applies_when_neither_is_set(self):
        self.assertEqual(resolve("", {}, "provider", "openai"), "openai")

    def test_an_empty_action_input_counts_as_unset(self):
        """An action input that is not passed arrives as "" rather than absent."""
        self.assertEqual(resolve("", {"max_comments": 3}, "max_comments", 5), 3)
        self.assertEqual(resolve(None, {"max_comments": 3}, "max_comments", 5), 3)

    def test_a_falsy_but_deliberate_value_is_respected(self):
        self.assertEqual(resolve(0, {"max_comments": 3}, "max_comments", 5), 0)


class ShippedExampleTests(unittest.TestCase):
    def test_the_example_file_parses_and_uses_only_known_keys(self):
        """A shipped example that the loader rejects would be embarrassing."""
        config = load(".genai-review.yml.example")
        self.assertIn("provider", config)
        self.assertIn("max_comments", config)
        self.assertEqual(config["mode"], "review")

    def test_the_example_does_not_contain_a_credential_key(self):
        text = Path(".genai-review.yml.example").read_text()
        self.assertNotIn("api_key:", text.replace("# There is deliberately no `api_key` key", ""))


if __name__ == "__main__":
    unittest.main()
