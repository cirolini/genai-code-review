"""
Tests for the review pressure controls.

The acceptance criterion is at the bottom: a noisy fixture pull request posts
at most `max_comments` inline comments plus one updated summary, and a second
push duplicates nothing.
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import sticky
from budget import apply_budget, fingerprint, priority, risk_map
from chunking import chunk_diff, estimate_tokens, split_diff_by_file
from findings import Finding
from panel import merge as merge_panel
from panel import parse_panel
from paths import DEFAULT_IGNORE_PATHS, is_ignored, parse_ignore_paths, partition
from providers.base import Usage
from review_run import ReviewSettings, RunReport, build_summary, execute


def make(file="a.py", severity="major", confidence=0.8, title=None, line=3, category="bug"):
    return Finding(
        file=file,
        line_start=line,
        line_end=line,
        severity=severity,
        category=category,
        confidence=confidence,
        title=title or f"{severity} in {file}",
        rationale="Because.",
    )


class IgnorePathTests(unittest.TestCase):
    def test_lockfiles_are_ignored_at_the_repository_root(self):
        """The root package-lock.json is the exact file the pattern exists for."""
        for path in ("package-lock.json", "go.sum", "poetry.lock", "Cargo.lock"):
            with self.subTest(path=path):
                self.assertTrue(is_ignored(path, DEFAULT_IGNORE_PATHS))

    def test_lockfiles_are_ignored_in_subdirectories(self):
        self.assertTrue(is_ignored("services/api/package-lock.json", DEFAULT_IGNORE_PATHS))

    def test_generated_vendored_and_minified_code_is_ignored(self):
        for path in (
            "web/node_modules/left-pad/index.js",
            "api/user_pb2.py",
            "vendor/github.com/x/y.go",
            "static/app.min.js",
            "tests/__snapshots__/view.snap",
            "db/migrations/0003_add_index.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_ignored(path, DEFAULT_IGNORE_PATHS))

    def test_ordinary_source_is_not_ignored(self):
        for path in ("src/app.py", "README.md", "lib/locks.py", "src/builder.py"):
            with self.subTest(path=path):
                self.assertFalse(is_ignored(path, DEFAULT_IGNORE_PATHS))

    def test_unset_means_defaults_and_empty_means_nothing_ignored(self):
        self.assertEqual(parse_ignore_paths(None), DEFAULT_IGNORE_PATHS)
        self.assertEqual(parse_ignore_paths(""), ())
        self.assertFalse(is_ignored("package-lock.json", parse_ignore_paths("")))

    def test_accepts_comma_or_newline_separated_globs(self):
        self.assertEqual(parse_ignore_paths("*.md, docs/**"), ("*.md", "docs/**"))
        self.assertEqual(parse_ignore_paths("*.md\ndocs/**"), ("*.md", "docs/**"))

    def test_partition_preserves_order(self):
        reviewable, ignored = partition(
            ["a.py", "package-lock.json", "b.py"], DEFAULT_IGNORE_PATHS
        )
        self.assertEqual(reviewable, ["a.py", "b.py"])
        self.assertEqual(ignored, ["package-lock.json"])


class BudgetTests(unittest.TestCase):
    def test_severity_outranks_confidence(self):
        """A half-sure blocker matters more than a certain nit."""
        self.assertGreater(
            priority(make(severity="blocker", confidence=0.5)),
            priority(make(severity="nit", confidence=1.0)),
        )

    def test_confidence_orders_within_a_severity(self):
        self.assertGreater(
            priority(make(severity="major", confidence=0.9)),
            priority(make(severity="major", confidence=0.4)),
        )

    def test_only_the_top_n_are_posted(self):
        findings = [make(severity="minor", confidence=c / 10) for c in range(1, 11)]
        outcome = apply_budget(findings, max_comments=3)
        self.assertEqual(len(outcome.posted), 3)
        self.assertEqual(len(outcome.over_budget), 7)

    def test_suppressed_findings_are_counted_not_lost(self):
        outcome = apply_budget([make() for _ in range(9)], max_comments=2)
        self.assertEqual(outcome.considered, 9)
        self.assertEqual(len(outcome.posted) + len(outcome.suppressed), 9)

    def test_min_severity_filters_out_the_trivial(self):
        findings = [make(severity=s) for s in ("blocker", "major", "minor", "nit")]
        outcome = apply_budget(findings, max_comments=10, min_severity="major")
        self.assertEqual({f.severity for f in outcome.posted}, {"blocker", "major"})
        self.assertEqual(len(outcome.below_threshold), 2)

    def test_min_confidence_filters_out_guesses(self):
        findings = [make(confidence=0.2), make(confidence=0.9, title="sure")]
        outcome = apply_budget(findings, max_comments=10, min_confidence=0.5)
        self.assertEqual([f.title for f in outcome.posted], ["sure"])

    def test_findings_already_posted_do_not_consume_budget(self):
        """
        A repeat finding must not push a new one out of the budget, which is
        why the already-posted filter runs before ranking.
        """
        old = make(title="known issue")
        new = make(title="new issue", severity="nit")
        outcome = apply_budget(
            [old, new], max_comments=1, already_posted_keys={fingerprint(old)}
        )
        self.assertEqual([f.title for f in outcome.posted], ["new issue"])
        self.assertEqual(len(outcome.already_posted), 1)

    def test_max_comments_zero_posts_nothing_but_still_counts(self):
        outcome = apply_budget([make() for _ in range(4)], max_comments=0)
        self.assertEqual(outcome.posted, [])
        self.assertEqual(len(outcome.over_budget), 4)


class FingerprintTests(unittest.TestCase):
    def test_line_numbers_are_not_part_of_the_identity(self):
        """
        A later push that adds an import shifts every line below it. Re-posting
        the same comment because the file moved down is the noise this phase
        exists to remove.
        """
        self.assertEqual(fingerprint(make(line=10)), fingerprint(make(line=42)))

    def test_title_whitespace_and_case_do_not_matter(self):
        self.assertEqual(
            fingerprint(make(title="SQL  Injection")), fingerprint(make(title="sql injection"))
        )

    def test_different_problems_in_one_file_stay_distinct(self):
        self.assertNotEqual(
            fingerprint(make(title="SQL injection", category="security")),
            fingerprint(make(title="Missing null check", category="bug")),
        )


class RiskMapTests(unittest.TestCase):
    def test_ranks_files_by_accumulated_risk_and_gives_a_reason(self):
        findings = [
            make(file="safe.py", severity="nit"),
            make(file="risky.py", severity="blocker"),
            make(file="risky.py", severity="major", title="second"),
        ]
        ranked = risk_map(findings)
        self.assertEqual(ranked[0][0], "risky.py")
        self.assertIn("2 findings", ranked[0][2])
        self.assertIn("blocker", ranked[0][2])


class StickyStateTests(unittest.TestCase):
    def test_state_survives_a_round_trip(self):
        state = sticky.build_state(last_reviewed_sha="abc123", posted_fingerprints=["a:b:c"])
        body = f"## Code review\n\nAll good.\n\n{sticky.render_state(state)}"
        self.assertEqual(sticky.parse_state(body), state)

    def test_state_is_invisible_in_the_rendered_body(self):
        rendered = sticky.render_state(
            sticky.build_state(last_reviewed_sha="abc", posted_fingerprints=[])
        )
        self.assertTrue(rendered.startswith("<!--"))
        self.assertTrue(rendered.rstrip().endswith("-->"))

    def test_unparseable_state_degrades_to_a_first_run(self):
        """A hand-edited body should cost a duplicate comment, not a failed run."""
        self.assertIsNone(sticky.parse_state("<!-- genai-code-review:state {oops -->"))
        self.assertIsNone(sticky.parse_state("a comment from a person"))
        self.assertIsNone(sticky.parse_state(None))

    def test_a_future_state_version_is_ignored_rather_than_misread(self):
        body = '<!-- genai-code-review:state\n{"version": 99}\n-->'
        self.assertIsNone(sticky.parse_state(body))

    def test_upsert_edits_the_existing_comment_instead_of_adding_one(self):
        existing = SimpleNamespace(
            body=sticky.render_state(
                sticky.build_state(last_reviewed_sha="old", posted_fingerprints=[])
            ),
            edit=MagicMock(),
        )
        github = MagicMock()
        github.get_pr_comments.return_value = [SimpleNamespace(body="unrelated"), existing]

        sticky.upsert(
            github, 1, "new body",
            sticky.build_state(last_reviewed_sha="new", posted_fingerprints=[]),
        )

        existing.edit.assert_called_once()
        github.post_comment.assert_not_called()

    def test_upsert_posts_when_there_is_no_previous_comment(self):
        github = MagicMock()
        github.get_pr_comments.return_value = [SimpleNamespace(body="someone else's comment")]
        sticky.upsert(
            github, 1, "body",
            sticky.build_state(last_reviewed_sha="x", posted_fingerprints=[]),
        )
        github.post_comment.assert_called_once()


class ChunkingTests(unittest.TestCase):
    PATCH = (
        "diff --git a/a.py b/a.py\n+++ b/a.py\n@@ -1,1 +1,2 @@\n+one\n"
        "diff --git a/b.py b/b.py\n+++ b/b.py\n@@ -1,1 +1,2 @@\n+two\n"
    )

    def test_splits_per_file(self):
        self.assertEqual([p for p, _ in split_diff_by_file(self.PATCH)], ["a.py", "b.py"])

    def test_the_word_diff_in_content_does_not_split(self):
        patch = (
            "diff --git a/x.py b/x.py\n+++ b/x.py\n@@ -1,1 +1,2 @@\n"
            "+# diff --git in a comment\n"
        )
        self.assertEqual(len(split_diff_by_file(patch)), 1)

    def test_files_are_grouped_until_the_budget_is_reached(self):
        chunks, skipped, truncated = chunk_diff(self.PATCH, max_tokens=100_000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual((skipped, truncated), ([], False))

    def test_an_oversized_file_is_skipped_whole_not_cut_in_half(self):
        """Half a file produces confident findings about code never seen."""
        huge = "diff --git a/big.py b/big.py\n+++ b/big.py\n@@ -1,1 +1,2 @@\n" + "+x\n" * 5000
        chunks, skipped, _ = chunk_diff(huge, max_tokens=100)
        self.assertEqual(chunks, [])
        self.assertEqual(skipped, ["big.py"])

    def test_too_many_chunks_reports_truncation_rather_than_pretending(self):
        patch = "".join(
            f"diff --git a/f{i}.py b/f{i}.py\n+++ b/f{i}.py\n@@ -1,1 +1,2 @@\n+x\n"
            for i in range(10)
        )
        chunks, skipped, truncated = chunk_diff(patch, max_tokens=30, max_chunks=2)
        self.assertTrue(truncated)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(skipped)

    def test_token_estimate_is_pessimistic_for_code(self):
        self.assertGreater(estimate_tokens("x" * 300), 90)


class PanelTests(unittest.TestCase):
    def test_parses_the_member_list(self):
        self.assertEqual(parse_panel("openai, anthropic"), ["openai", "anthropic"])
        self.assertEqual(parse_panel(""), [])
        self.assertEqual(parse_panel("openai,openai"), ["openai"])

    def test_agreement_raises_confidence(self):
        a = make(title="SQL injection", confidence=0.6)
        b = make(title="SQL injection", confidence=0.6)
        outcome = merge_panel([("m1", [a]), ("m2", [b])])
        self.assertEqual(len(outcome.findings), 1)
        self.assertEqual(outcome.agreed_count, 1)
        self.assertGreater(outcome.findings[0].confidence, 0.6)

    def test_a_solo_finding_is_demoted_not_dropped(self):
        """One model spotting a real blocker the other missed is worth keeping."""
        outcome = merge_panel([("m1", [make(confidence=0.8)]), ("m2", [])])
        self.assertEqual(len(outcome.findings), 1)
        self.assertLess(outcome.findings[0].confidence, 0.8)

    def test_agreement_rate_is_none_when_there_was_nothing_to_agree_about(self):
        """0% on an empty review would be a misleading number, not a neutral one."""
        self.assertIsNone(merge_panel([("m1", []), ("m2", [])]).agreement_rate)

    def test_agreement_is_reported(self):
        outcome = merge_panel(
            [
                ("m1", [make(title="both"), make(title="only m1")]),
                ("m2", [make(title="both")]),
            ]
        )
        self.assertEqual(outcome.agreed_count, 1)
        self.assertEqual(outcome.solo_count, 1)
        self.assertEqual(outcome.agreement_rate, 0.5)


class SummaryHonestyTests(unittest.TestCase):
    def _report(self, **kwargs):
        report = RunReport(head_sha="abc1234")
        report.results = [
            SimpleNamespace(
                provider="openai", model="m", usage=Usage(10, 5), latency_s=1.0
            )
        ]
        for key, value in kwargs.items():
            setattr(report, key, value)
        return report

    def test_reports_suppressed_findings_with_how_to_see_them(self):
        report = self._report()
        report.all_findings = [make() for _ in range(8)]
        report.budget = apply_budget(report.all_findings, max_comments=2)
        body = build_summary(report, MagicMock(paths=[]))

        self.assertIn("6 finding(s) not posted", body)
        self.assertIn("max_comments", body)
        self.assertIn("not discarded", body)

    def test_reports_ignored_and_skipped_files(self):
        report = self._report(
            ignored_paths=["package-lock.json"], skipped_paths=["huge.py"], truncated=True
        )
        report.all_findings = [make()]
        report.budget = apply_budget(report.all_findings)
        body = build_summary(report, MagicMock(paths=[]))

        self.assertIn("Not reviewed", body)
        self.assertIn("ignore_paths", body)
        self.assertIn("huge.py", body)
        self.assertIn("splitting it", body)

    def test_says_plainly_when_nothing_was_reviewed(self):
        report = self._report(parse_failed=True)
        report.budget = apply_budget([])
        self.assertIn("was not reviewed", build_summary(report, MagicMock(paths=[])))

    def test_an_incremental_run_says_what_it_skipped(self):
        report = self._report(incremental=True, base_sha="0123456789")
        report.all_findings = [make()]
        report.budget = apply_budget(report.all_findings)
        body = build_summary(report, MagicMock(paths=[]))
        self.assertIn("Only changes since `0123456`", body)

    def test_a_clean_review_gives_a_verdict_not_silence(self):
        report = self._report()
        report.budget = apply_budget([])
        self.assertIn("Nothing worth flagging", build_summary(report, MagicMock(paths=[])))

    def test_the_verdict_points_at_the_worst_finding(self):
        report = self._report()
        report.all_findings = [make(severity="blocker", file="auth.py")]
        report.budget = apply_budget(report.all_findings)
        body = build_summary(report, MagicMock(paths=[]))
        self.assertIn("blocker", body)
        self.assertIn("auth.py", body)
        self.assertIn("Start there", body)


NOISY_PATCH = "".join(
    f"diff --git a/mod{i}.py b/mod{i}.py\n"
    f"--- a/mod{i}.py\n+++ b/mod{i}.py\n@@ -1,2 +1,4 @@\n import os\n+x = {i}\n+y = {i}\n"
    for i in range(6)
) + (
    "diff --git a/package-lock.json b/package-lock.json\n"
    "--- a/package-lock.json\n+++ b/package-lock.json\n@@ -1,1 +1,2 @@\n"
    '+  "lockfileVersion": 3,\n'
)


def noisy_findings(count=14):
    severities = ["nit", "minor", "major", "blocker"]
    return [
        {
            "file": f"mod{i % 6}.py",
            "line_start": 2,
            "line_end": 2,
            "severity": severities[i % 4],
            "category": "style",
            "confidence": 0.5 + (i % 5) / 10,
            "title": f"Issue number {i}",
            "rationale": "Something to say.",
        }
        for i in range(count)
    ]


class FakeGithub:
    """Records what a run posted, so a second run can be checked against it."""

    def __init__(self, patch):
        self.patch = patch
        self.comments = []
        self.reviews = []
        self.head_sha = "sha-one"
        # What the compare endpoint reports; tests override it to simulate a
        # rebase or a merge from the base branch.
        self.comparison = {"status": "ahead", "total_commits": 1,
                           "commits": [{"parents": [{"sha": "p"}]}]}
        self.compare_patch = None
        self.fail_reviews = False

    def get_pr_head_sha(self, pr_id):
        return self.head_sha

    def get_pr_patch(self, pr_id):
        return self.patch

    def get_compare(self, base, head):
        return self.comparison

    def get_compare_patch(self, base, head):
        return self.patch if self.compare_patch is None else self.compare_patch

    def get_pr_comments(self, pr_id):
        return list(self.comments)

    def post_comment(self, pr_id, body):
        comment = SimpleNamespace(body=body)
        comment.edit = lambda new_body, c=comment: setattr(c, "body", new_body)
        self.comments.append(comment)
        return comment

    def create_review(self, pr_id, comments, body):
        if self.fail_reviews:
            raise RuntimeError("422 Unprocessable Entity")
        self.reviews.append(comments)
        return {"id": len(self.reviews)}

    @property
    def inline_comments(self):
        return [c for review in self.reviews for c in review]


def provider_returning(findings_dicts):
    provider = MagicMock()
    provider.name = "openai"
    provider.model = "gpt-test"
    provider.review.return_value = SimpleNamespace(
        text=json.dumps({"findings": findings_dicts}),
        provider="openai",
        model="gpt-test",
        usage=Usage(500, 100),
        latency_s=2.0,
        attempts=1,
    )
    return provider


class AcceptanceTests(unittest.TestCase):
    """
    Phase 3, done when: on a noisy pull request the bot posts at most
    max_comments inline comments plus one updated summary, and a second push
    does not duplicate anything.
    """

    def setUp(self):
        self.github = FakeGithub(NOISY_PATCH)
        self.provider = provider_returning(noisy_findings(14))
        self.settings = ReviewSettings(max_comments=5)

    def run_once(self):
        return execute(self.github, lambda _: self.provider, 1, self.settings)

    def test_a_noisy_pr_is_held_to_the_comment_budget(self):
        report = self.run_once()
        self.assertLessEqual(len(self.github.inline_comments), 5)
        self.assertEqual(len(report.budget.posted), 5)
        self.assertGreater(len(report.budget.suppressed), 0)

    def test_exactly_one_summary_comment_is_posted(self):
        self.run_once()
        self.assertEqual(len(self.github.comments), 1)

    def test_the_most_serious_findings_are_the_ones_posted(self):
        report = self.run_once()
        self.assertTrue(all(f.severity in ("blocker", "major") for f in report.budget.posted))

    def test_ignored_files_never_reach_the_model(self):
        self.run_once()
        prompt = self.provider.review.call_args.args[0]
        self.assertNotIn("package-lock.json", prompt)

    def test_a_second_push_updates_the_summary_instead_of_adding_one(self):
        self.run_once()
        self.github.head_sha = "sha-two"
        self.run_once()
        self.assertEqual(len(self.github.comments), 1)

    def test_a_second_push_does_not_repeat_findings_already_posted(self):
        first = self.run_once()
        first_titles = {f.title for f in first.budget.posted}

        self.github.head_sha = "sha-two"
        second = self.run_once()
        second_titles = {f.title for f in second.budget.posted}

        self.assertEqual(first_titles & second_titles, set())
        self.assertEqual(len(second.budget.already_posted), len(first_titles))

    def test_the_second_run_reviews_only_what_is_new(self):
        self.run_once()
        self.github.head_sha = "sha-two"
        report = self.run_once()
        self.assertTrue(report.incremental)
        self.assertEqual(report.base_sha, "sha-one")

    def test_the_summary_carries_state_forward(self):
        self.run_once()
        state = sticky.parse_state(self.github.comments[0].body)
        self.assertEqual(state["last_reviewed_sha"], "sha-one")
        self.assertEqual(len(state["posted"]), 5)

    def test_every_posted_comment_lands_on_a_line_in_the_diff(self):
        self.run_once()
        for comment in self.github.inline_comments:
            self.assertEqual(comment["side"], "RIGHT")
            self.assertIn(comment["path"], [f"mod{i}.py" for i in range(6)])

    def test_deleted_and_binary_files_are_not_sent_to_the_model(self):
        """
        A finding on either is rejected at placement time anyway — there is no
        line in the new file to attach to — so sending them only costs tokens.
        """
        patch = (
            "diff --git a/live.py b/live.py\n--- a/live.py\n+++ b/live.py\n"
            "@@ -1,1 +1,2 @@\n import os\n+x = 1\n"
            "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\n"
            "--- a/gone.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-old = True\n"
            "diff --git a/pic.bin b/pic.bin\nBinary files a/pic.bin and b/pic.bin differ\n"
        )
        github = FakeGithub(patch)
        execute(github, lambda _: self.provider, 1, ReviewSettings(ignore_paths=()))

        prompt = self.provider.review.call_args.args[0]
        self.assertIn("live.py", prompt)
        self.assertNotIn("gone.py", prompt)
        self.assertNotIn("pic.bin", prompt)

    def test_nothing_to_review_still_produces_a_summary(self):
        github = FakeGithub(
            "diff --git a/package-lock.json b/package-lock.json\n"
            "--- a/package-lock.json\n+++ b/package-lock.json\n@@ -1,1 +1,2 @@\n+x\n"
        )
        settings = ReviewSettings(ignore_paths=DEFAULT_IGNORE_PATHS)
        execute(github, lambda _: self.provider, 1, settings)
        self.assertEqual(len(github.comments), 1)
        self.assertIn("No reviewable files", github.comments[0].body)


class NothingIsForgottenTests(unittest.TestCase):
    """
    State moves forward only for what actually happened.

    The summary's promise is that it says what was not reviewed. If the last
    reviewed SHA advanced past a run that skipped files, the next push would
    diff from there and those files would drop out of the summary unreviewed.
    """

    def setUp(self):
        self.github = FakeGithub(NOISY_PATCH)
        self.provider = provider_returning(noisy_findings(4))
        self.settings = ReviewSettings(max_comments=5)

    def run_once(self):
        return execute(self.github, lambda _: self.provider, 1, self.settings)

    def state(self):
        return sticky.parse_state(self.github.comments[0].body)

    def test_an_incomplete_run_does_not_advance_the_reviewed_sha(self):
        self.provider.review.return_value.text = "not json at all"
        report = self.run_once()
        self.assertTrue(report.parse_failed)
        self.assertIsNone(self.state()["last_reviewed_sha"])
        self.assertIn("next push reviews the whole pull request again",
                      self.github.comments[0].body)

    def test_an_incomplete_second_run_keeps_the_previous_base(self):
        self.run_once()
        self.github.head_sha = "sha-two"
        self.provider.review.return_value.text = "not json at all"
        self.run_once()
        self.assertEqual(self.state()["last_reviewed_sha"], "sha-one")

    def test_a_complete_run_advances_the_reviewed_sha(self):
        self.run_once()
        self.assertEqual(self.state()["last_reviewed_sha"], "sha-one")

    def test_findings_are_not_marked_posted_when_the_review_is_rejected(self):
        self.github.fail_reviews = True
        report = self.run_once()
        self.assertTrue(report.post_failed)
        self.assertEqual(self.state()["posted"], [])
        self.assertIsNone(self.state()["last_reviewed_sha"])

    def test_a_rejected_review_lists_its_findings_in_the_summary(self):
        self.github.fail_reviews = True
        report = self.run_once()
        body = self.github.comments[0].body
        self.assertIn("GitHub rejected the inline comments", body)
        for finding in report.budget.posted:
            self.assertIn(finding.title, body)

    def test_findings_rejected_once_are_posted_on_the_next_push(self):
        self.github.fail_reviews = True
        first = self.run_once()
        self.github.fail_reviews = False
        self.github.head_sha = "sha-two"
        second = self.run_once()
        self.assertEqual({f.title for f in second.budget.posted},
                         {f.title for f in first.budget.posted})


class IncrementalSafetyTests(unittest.TestCase):
    """After a rebase or a merge from main, the compare diff is not the PR's."""

    def setUp(self):
        self.github = FakeGithub(NOISY_PATCH)
        self.provider = provider_returning(noisy_findings(2))
        self.settings = ReviewSettings(max_comments=5)
        execute(self.github, lambda _: self.provider, 1, self.settings)
        self.github.head_sha = "sha-two"

    def run_again(self):
        return execute(self.github, lambda _: self.provider, 1, self.settings)

    def test_a_rewritten_history_falls_back_to_the_whole_pull_request(self):
        self.github.comparison = {"status": "diverged", "commits": []}
        report = self.run_again()
        self.assertFalse(report.incremental)
        self.assertIn("rewritten", report.full_review_reason)
        self.assertIn("reviewed again", self.github.comments[0].body)

    def test_a_merge_from_the_base_branch_falls_back_to_the_whole_pull_request(self):
        self.github.comparison = {
            "status": "ahead",
            "total_commits": 1,
            "commits": [{"parents": [{"sha": "a"}, {"sha": "b"}]}],
        }
        report = self.run_again()
        self.assertFalse(report.incremental)
        self.assertIn("merge", report.full_review_reason)

    def test_files_outside_the_pull_request_are_never_reviewed(self):
        """Defence in depth, if something from main slips into the range."""
        self.github.compare_patch = NOISY_PATCH + (
            "diff --git a/from_main.py b/from_main.py\n"
            "--- a/from_main.py\n+++ b/from_main.py\n@@ -1,1 +1,2 @@\n x\n+y\n"
        )
        self.provider = provider_returning([{
            "file": "from_main.py", "line_start": 2, "line_end": 2,
            "severity": "blocker", "category": "bug", "confidence": 0.9,
            "title": "Not this pull request's code", "rationale": "r",
        }])
        report = self.run_again()
        self.assertTrue(report.incremental)
        self.assertNotIn("from_main.py", self.provider.review.call_args.args[0])
        self.assertEqual(report.budget.posted, [])


class RelocatedSuggestionTests(unittest.TestCase):
    """A suggestion written for lines 10-11 must not be committed onto 12-13."""

    PATCH = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        "@@ -1,1 +1,3 @@\n import os\n+x = 1\n+y = 2\n"
    )

    def finding(self, line):
        return {
            "file": "a.py", "line_start": line, "line_end": line,
            "severity": "major", "category": "bug", "confidence": 0.9,
            "title": "Wrong value", "rationale": "r", "suggestion": "x = 2",
        }

    def posted_body(self, line):
        github = FakeGithub(self.PATCH)
        provider = provider_returning([self.finding(line)])
        execute(github, lambda _: provider, 1, ReviewSettings(ignore_paths=()))
        return github.inline_comments[0]["body"]

    def test_an_exact_finding_keeps_its_one_click_suggestion(self):
        self.assertIn("```suggestion", self.posted_body(2))

    def test_a_snapped_finding_loses_its_one_click_suggestion(self):
        body = self.posted_body(5)
        self.assertNotIn("```suggestion", body)
        self.assertIn("x = 2", body)


if __name__ == "__main__":
    unittest.main()
