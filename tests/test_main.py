import unittest
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock, patch

from main import (
    create_review_prompt,
    format_review_comment,
    get_env_vars,
    main,
    process_files,
    process_patch,
    report_provider_failure,
)
from providers import ProviderError
from providers.base import Usage

V2_ENV = {
    "GITHUB_TOKEN": "gh-token",
    "GITHUB_PR_ID": "1",
    "OPENAI_API_KEY": "openai-key",
    "OPENAI_MODEL": "gpt-legacy",
    "OPENAI_TEMPERATURE": "0.3",
    "OPENAI_MAX_TOKENS": "1234",
    "MODE": "files",
    "LANGUAGE": "en",
}


def result(text="a review", provider="openai", model="m", latency=1.5):
    return SimpleNamespace(
        text=text,
        provider=provider,
        model=model,
        usage=Usage(10, 20),
        latency_s=latency,
        attempts=1,
    )


class EnvResolutionTests(unittest.TestCase):
    """
    The v2 inputs must keep working. A workflow pinned to @v2 that upgrades to
    v3 without editing anything is the compatibility promise in ground rule 2.
    """

    def test_v2_only_workflow_still_resolves(self):
        with patch.dict("os.environ", V2_ENV, clear=True):
            env = get_env_vars()

        self.assertEqual(env["PROVIDER"], "openai")
        self.assertEqual(env["MODEL"], "gpt-legacy")
        self.assertEqual(env["API_KEY"], "openai-key")
        self.assertEqual(env["TEMPERATURE"], 0.3)
        self.assertEqual(env["MAX_TOKENS"], 1234)
        self.assertEqual(env["GITHUB_PR_ID"], 1)

    def test_v3_inputs_take_precedence_over_the_v2_aliases(self):
        env_vars = dict(
            V2_ENV,
            PROVIDER="anthropic",
            MODEL="claude-new",
            API_KEY="anthropic-key",
            TEMPERATURE="0.9",
            MAX_TOKENS="4096",
        )
        with patch.dict("os.environ", env_vars, clear=True):
            env = get_env_vars()

        self.assertEqual(env["PROVIDER"], "anthropic")
        self.assertEqual(env["MODEL"], "claude-new")
        self.assertEqual(env["API_KEY"], "anthropic-key")
        self.assertEqual(env["TEMPERATURE"], 0.9)
        self.assertEqual(env["MAX_TOKENS"], 4096)

    def test_empty_v3_input_falls_through_to_the_v2_alias(self):
        """An unset action input arrives as "", not as an absent variable."""
        env_vars = dict(V2_ENV, MODEL="", API_KEY="", TEMPERATURE="", MAX_TOKENS="")
        with patch.dict("os.environ", env_vars, clear=True):
            env = get_env_vars()

        self.assertEqual(env["MODEL"], "gpt-legacy")
        self.assertEqual(env["API_KEY"], "openai-key")
        self.assertEqual(env["TEMPERATURE"], 0.3)
        self.assertEqual(env["MAX_TOKENS"], 1234)

    def test_model_may_be_unset_so_the_provider_default_applies(self):
        env_vars = {k: v for k, v in V2_ENV.items() if k != "OPENAI_MODEL"}
        with patch.dict("os.environ", env_vars, clear=True):
            env = get_env_vars()
        self.assertIsNone(env["MODEL"])

    def test_mode_defaults_to_review_in_v3(self):
        """
        v3 defaults to inline comments. A v2 workflow that set `mode`
        explicitly is unaffected; one that did not gets the new behaviour on a
        major version bump, which is what a major version is for.
        """
        env_vars = {k: v for k, v in V2_ENV.items() if k not in ("MODE", "LANGUAGE")}
        with patch.dict("os.environ", env_vars, clear=True):
            env = get_env_vars()
        self.assertEqual(env["MODE"], "review")
        self.assertEqual(env["LANGUAGE"], "en")

    def test_an_explicit_v2_mode_is_still_honoured(self):
        for mode in ("files", "patch"):
            with self.subTest(mode=mode):
                with patch.dict("os.environ", dict(V2_ENV, MODE=mode), clear=True):
                    self.assertEqual(get_env_vars()["MODE"], mode)

    def test_missing_github_token_is_rejected(self):
        env_vars = {k: v for k, v in V2_ENV.items() if k != "GITHUB_TOKEN"}
        with patch.dict("os.environ", env_vars, clear=True):
            with self.assertRaises(ValueError):
                get_env_vars()

    def test_non_numeric_pr_id_is_rejected_with_a_clear_message(self):
        with patch.dict("os.environ", dict(V2_ENV, GITHUB_PR_ID="not-a-number"), clear=True):
            with self.assertRaises(ValueError) as ctx:
                get_env_vars()
        self.assertIn("GITHUB_PR_ID", str(ctx.exception))


class ProviderDefaultTests(unittest.TestCase):
    """
    v3 defaults to gemini, the provider with measured results behind it. But a
    v2 workflow passes `openai_api_key` and no `provider`, and moving the
    default would send an OpenAI key to Google.
    """

    BASE: ClassVar[dict] = {"GITHUB_TOKEN": "t", "GITHUB_PR_ID": "1"}

    def test_defaults_to_gemini_for_a_fresh_workflow(self):
        with patch.dict("os.environ", dict(self.BASE, API_KEY="k"), clear=True):
            self.assertEqual(get_env_vars()["PROVIDER"], "gemini")

    def test_a_v2_workflow_stays_on_openai(self):
        with patch.dict("os.environ", dict(self.BASE, OPENAI_API_KEY="k"), clear=True):
            self.assertEqual(get_env_vars()["PROVIDER"], "openai")

    def test_an_explicit_provider_always_wins(self):
        env = dict(self.BASE, OPENAI_API_KEY="k", PROVIDER="anthropic")
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(get_env_vars()["PROVIDER"], "anthropic")

    def test_the_v3_key_input_does_not_imply_openai(self):
        """`api_key` is provider-neutral; only the v2-only alias implies OpenAI."""
        env = dict(self.BASE, API_KEY="k", OPENAI_API_KEY="legacy")
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(get_env_vars()["PROVIDER"], "gemini")

    def test_no_key_at_all_still_defaults_to_gemini(self):
        with patch.dict("os.environ", dict(self.BASE), clear=True):
            self.assertEqual(get_env_vars()["PROVIDER"], "gemini")


class MainDispatchTests(unittest.TestCase):
    @patch("main.build_provider")
    @patch("main.GithubClient")
    @patch("main.get_env_vars")
    def test_files_mode(self, mock_env, mock_github, mock_build):
        mock_env.return_value = _resolved(mode="files")
        with patch("main.process_files") as mock_process:
            main()
        mock_process.assert_called_once()

    @patch("main.build_provider")
    @patch("main.GithubClient")
    @patch("main.get_env_vars")
    def test_patch_mode(self, mock_env, mock_github, mock_build):
        mock_env.return_value = _resolved(mode="patch")
        with patch("main.process_patch") as mock_process:
            main()
        mock_process.assert_called_once()

    @patch("main.build_provider")
    @patch("main.GithubClient")
    @patch("main.get_env_vars")
    def test_invalid_mode_raises(self, mock_env, mock_github, mock_build):
        mock_env.return_value = _resolved(mode="sideways")
        with self.assertRaises(ValueError):
            main()

    @patch("main.build_provider")
    @patch("main.GithubClient")
    @patch("main.get_env_vars")
    def test_provider_failure_is_reported_on_the_pr_and_reraised(
        self, mock_env, mock_github, mock_build
    ):
        """
        A review that silently did not happen looks exactly like a clean review.
        The failure has to reach the pull request and fail the check.
        """
        mock_env.return_value = _resolved(mode="files")
        mock_build.side_effect = ProviderError(
            "the API key was rejected (401).", provider="openai", model="gpt-test"
        )

        with self.assertRaises(ProviderError):
            main()

        body = mock_github.return_value.post_comment.call_args.args[1]
        self.assertIn("Code review did not run", body)
        self.assertIn("401", body)


class FailureCommentTests(unittest.TestCase):
    def test_a_failure_to_comment_does_not_mask_the_original_error(self):
        github = MagicMock()
        github.post_comment.side_effect = RuntimeError("no write permission")
        error = ProviderError("boom", provider="openai", model="m")
        # Must not raise: the caller re-raises the provider error afterwards.
        report_provider_failure(github, 1, error)


class CommentFormattingTests(unittest.TestCase):
    def test_footer_names_the_provider_model_and_cost(self):
        body = format_review_comment(result(provider="anthropic", model="claude-x"))
        self.assertIn("a review", body)
        self.assertIn("anthropic", body)
        self.assertIn("claude-x", body)
        self.assertIn("10 in / 20 out", body)
        self.assertIn("1.5s", body)

    def test_no_longer_claims_every_review_came_from_chatgpt(self):
        self.assertNotIn("ChatGPT", format_review_comment(result(provider="gemini")))

    def test_missing_token_counts_are_omitted_rather_than_shown_as_none(self):
        no_usage = result()
        no_usage.usage = Usage(None, None)
        body = format_review_comment(no_usage)
        self.assertNotIn("None", body)


class ProcessingTests(unittest.TestCase):
    def test_process_files_posts_the_review(self):
        github, provider = MagicMock(), MagicMock()
        provider.review.return_value = result()
        github.get_pr.return_value.get_commits.return_value = [MagicMock(sha="abc123")]

        process_files(github, provider, 1, "en", None)

        github.get_pr.assert_called_with(1)
        provider.review.assert_called_once()
        github.post_comment.assert_called_once()

    def test_process_files_does_nothing_without_commits(self):
        github, provider = MagicMock(), MagicMock()
        github.get_pr.return_value.get_commits.return_value = []

        process_files(github, provider, 1, "en", None)

        provider.review.assert_not_called()

    def test_process_patch_posts_the_review(self):
        github, provider = MagicMock(), MagicMock()
        provider.review.return_value = result()
        github.get_pr_patch.return_value = "diff --git a/file b/file"

        process_patch(github, provider, 1, "en", None)

        github.get_pr_patch.assert_called_with(1)
        provider.review.assert_called_once()

    def test_empty_patch_says_so_instead_of_calling_the_model(self):
        github, provider = MagicMock(), MagicMock()
        github.get_pr_patch.return_value = ""

        process_patch(github, provider, 1, "en", None)

        provider.review.assert_not_called()
        github.post_comment.assert_called_once()


class PromptTests(unittest.TestCase):
    def test_default_prompt(self):
        prompt = create_review_prompt("def foo(): pass", "en", None)
        self.assertIn("Please review the following code", prompt)
        self.assertIn("def foo(): pass", prompt)

    def test_custom_prompt_replaces_the_default(self):
        prompt = create_review_prompt("x = 1", "pt-br", "Rate this 1-10:")
        self.assertIn("Rate this 1-10:", prompt)
        self.assertNotIn("Please review the following code", prompt)
        self.assertIn("pt-br", prompt)


def _resolved(mode="files"):
    return {
        "GITHUB_TOKEN": "gh-token",
        "GITHUB_PR_ID": 1,
        "PROVIDER": "openai",
        "MODEL": "gpt-test",
        "API_KEY": "key",
        "BASE_URL": None,
        "TEMPERATURE": 0.5,
        "MAX_TOKENS": 2048,
        "MODE": mode,
        "LANGUAGE": "en",
        "CUSTOM_PROMPT": None,
    }


if __name__ == "__main__":
    unittest.main()
