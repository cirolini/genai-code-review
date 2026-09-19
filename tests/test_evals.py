"""
Tests for the eval harness.

The harness is what turns claims about the reviewer into numbers, so it has to
be right about the numbers. Everything here runs against a stub provider: no
key, no network, no cost.
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from evals.cases import ExpectedDefect, load_cases, matches
from evals.metrics import Scores, score_case
from evals.report import full_report, summary_table
from evals.run import review_case

from findings import Finding
from providers.base import Usage
from runlog import build as build_runlog
from runlog import estimate_cost


def finding(file="app/users.py", line=12, category="security", severity="major", title="SQLi"):
    return Finding(
        file=file,
        line_start=line,
        line_end=line,
        severity=severity,
        category=category,
        confidence=0.9,
        title=title,
        rationale="Because.",
    )


def defect(file="app/users.py", line=12, categories=("security",)):
    return ExpectedDefect(file=file, line=line, categories=categories)


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.cases = load_cases()

    def test_the_set_is_the_documented_size(self):
        self.assertGreaterEqual(len(self.cases), 15)
        self.assertLessEqual(len(self.cases), 25)

    def test_it_contains_both_seeded_and_clean_diffs(self):
        """Without clean diffs there is no way to measure noise."""
        self.assertGreater(sum(1 for c in self.cases if not c.is_clean), 10)
        self.assertGreaterEqual(sum(1 for c in self.cases if c.is_clean), 5)

    def test_the_defect_classes_from_the_plan_are_covered(self):
        names = {c.name for c in self.cases}
        for required in (
            "off_by_one",
            "sql_injection",
            "missing_null_check",
            "race_condition",
            "leaked_secret",
            "n_plus_one",
            "missing_test",
        ):
            with self.subTest(defect=required):
                self.assertIn(required, names)

    def test_every_seeded_defect_points_at_a_line_in_its_own_diff(self):
        """A defect labelled on a line the diff does not contain is unfindable."""
        from diff import parse_diff

        for case in self.cases:
            parsed = parse_diff(case.diff)
            for expected in case.expected:
                with self.subTest(case=case.name):
                    diff_file = parsed.get(expected.file)
                    self.assertIsNotNone(diff_file, f"{case.name}: {expected.file} not in diff")
                    nearest = diff_file.nearest_commentable_line(expected.line)
                    self.assertIsNotNone(nearest)
                    self.assertLessEqual(abs(nearest - expected.line), 4)

    def test_every_case_has_a_note_explaining_what_was_seeded(self):
        for case in self.cases:
            with self.subTest(case=case.name):
                self.assertTrue(case.note.strip())


class MatchingTests(unittest.TestCase):
    def test_an_exact_hit_matches(self):
        self.assertTrue(matches(finding(), defect()))

    def test_a_nearby_line_still_counts(self):
        """Pointing at the call rather than the assignment is still finding it."""
        self.assertTrue(matches(finding(line=14), defect(line=12)))

    def test_a_distant_line_does_not(self):
        self.assertFalse(matches(finding(line=60), defect(line=12)))

    def test_the_wrong_file_does_not(self):
        self.assertFalse(matches(finding(file="other.py"), defect()))

    def test_any_plausible_category_counts(self):
        """
        Penalising `bug` versus `security` for SQL injection would measure
        taxonomy agreement, not detection.
        """
        self.assertTrue(matches(finding(category="bug"), defect(categories=("security", "bug"))))
        self.assertFalse(matches(finding(category="style"), defect(categories=("security",))))


class ScoringTests(unittest.TestCase):
    def test_a_found_defect_is_a_true_positive(self):
        case = SimpleNamespace(name="c", is_clean=False, expected=[defect()])
        result = score_case(case, [finding()], [finding()])
        self.assertEqual(len(result.found), 1)
        self.assertEqual(result.missed, [])

    def test_a_missed_defect_is_recorded_with_its_identity(self):
        case = SimpleNamespace(name="c", is_clean=False, expected=[defect()])
        result = score_case(case, [], [])
        self.assertEqual(len(result.missed), 1)
        self.assertEqual(result.missed[0].file, "app/users.py")

    def test_an_unmatched_finding_is_spurious(self):
        case = SimpleNamespace(name="c", is_clean=False, expected=[defect()])
        result = score_case(case, [finding(), finding(line=80, title="invented")], [])
        self.assertEqual(len(result.found), 1)
        self.assertEqual(len(result.spurious), 1)

    def test_one_finding_cannot_satisfy_two_defects(self):
        case = SimpleNamespace(name="c", is_clean=False, expected=[defect(), defect()])
        result = score_case(case, [finding()], [])
        self.assertEqual(len(result.found), 1)
        self.assertEqual(len(result.missed), 1)

    def test_precision_recall_and_f1(self):
        scores = Scores()
        good = SimpleNamespace(name="a", is_clean=False, expected=[defect()])
        missed = SimpleNamespace(name="b", is_clean=False, expected=[defect()])
        scores.cases.append(score_case(good, [finding()], [finding()]))
        scores.cases.append(score_case(missed, [], []))

        self.assertEqual(scores.true_positives, 1)
        self.assertEqual(scores.false_negatives, 1)
        self.assertEqual(scores.precision, 1.0)
        self.assertEqual(scores.recall, 0.5)
        self.assertAlmostEqual(scores.f1, 2 / 3)

    def test_noise_rate_counts_clean_diffs_that_drew_a_comment(self):
        scores = Scores()
        clean = SimpleNamespace(name="clean", is_clean=True, expected=[])
        quiet = SimpleNamespace(name="quiet", is_clean=True, expected=[])
        scores.cases.append(score_case(clean, [finding()], [finding()]))
        scores.cases.append(score_case(quiet, [], []))
        self.assertEqual(scores.noise_rate, 0.5)

    def test_noise_rate_is_none_without_clean_diffs(self):
        self.assertIsNone(Scores().noise_rate)

    def test_metrics_are_none_rather_than_zero_when_undefined(self):
        """Reporting 0% precision on an empty run would be a false claim."""
        empty = Scores()
        self.assertIsNone(empty.precision)
        self.assertIsNone(empty.recall)
        self.assertIsNone(empty.f1)


class StubProvider:
    """Returns a scripted response without a key or a network call."""

    name = "stub"
    model = "stub-1"

    def __init__(self, findings_by_file=None):
        self.findings_by_file = findings_by_file or {}
        self.prompts = []

    def review(self, prompt, schema=None):
        self.prompts.append(prompt)
        payload = []
        for path, items in self.findings_by_file.items():
            if path in prompt:
                payload.extend(items)
        return SimpleNamespace(
            text=json.dumps({"findings": payload}),
            provider=self.name,
            model=self.model,
            usage=Usage(1000, 200),
            latency_s=1.5,
            attempts=1,
        )


class EndToEndTests(unittest.TestCase):
    def test_a_perfect_reviewer_scores_perfectly_on_a_seeded_case(self):
        [case] = load_cases(only={"sql_injection"})
        expected = case.expected[0]
        provider = StubProvider(
            {
                expected.file: [
                    {
                        "file": expected.file,
                        "line_start": expected.line,
                        "line_end": expected.line,
                        "severity": "blocker",
                        "category": "security",
                        "confidence": 0.95,
                        "title": "SQL injection",
                        "rationale": "Interpolated into the query.",
                    }
                ]
            }
        )
        result = review_case(case, [provider], 5, "nit", 0.0)
        self.assertEqual(len(result.found), 1)
        self.assertEqual(result.missed, [])
        self.assertEqual(result.spurious, [])

    def test_a_silent_reviewer_scores_zero_recall_and_no_noise(self):
        cases = load_cases(only={"sql_injection", "clean_rename"})
        provider = StubProvider()
        scores = Scores()
        for case in cases:
            scores.cases.append(review_case(case, [provider], 5, "nit", 0.0))

        self.assertEqual(scores.recall, 0.0)
        self.assertEqual(scores.noise_rate, 0.0)

    def test_a_chatty_reviewer_is_penalised_on_clean_diffs(self):
        [case] = load_cases(only={"clean_rename"})
        provider = StubProvider(
            {
                "lib/format.py": [
                    {
                        "file": "lib/format.py",
                        "line_start": 5,
                        "line_end": 5,
                        "severity": "nit",
                        "category": "style",
                        "confidence": 0.4,
                        "title": "Consider a different name",
                        "rationale": "Taste.",
                    }
                ]
            }
        )
        scores = Scores()
        scores.cases.append(review_case(case, [provider], 5, "nit", 0.0))
        self.assertEqual(scores.noise_rate, 1.0)

    def test_the_budget_limits_what_counts_as_posted(self):
        [case] = load_cases(only={"clean_rename"})
        noisy = [
            {
                "file": "lib/format.py",
                "line_start": 5,
                "line_end": 5,
                "severity": "nit",
                "category": "style",
                "confidence": 0.3,
                "title": f"Nit {i}",
                "rationale": "Taste.",
            }
            for i in range(9)
        ]
        provider = StubProvider({"lib/format.py": noisy})
        result = review_case(case, [provider], 2, "nit", 0.0)
        self.assertEqual(result.posted_count, 2)

    def test_the_fixture_diff_reaches_the_model(self):
        [case] = load_cases(only={"sql_injection"})
        provider = StubProvider()
        review_case(case, [provider], 5, "nit", 0.0)
        self.assertIn("app/users.py", provider.prompts[0])


class ReportTests(unittest.TestCase):
    def test_the_table_renders_every_metric(self):
        scores = Scores()
        good = SimpleNamespace(name="a", is_clean=False, expected=[defect()])
        scores.cases.append(score_case(good, [finding()], [finding()], cost=0.002, latency=1.0))

        table = summary_table([("stub", scores)])
        self.assertIn("Precision", table)
        self.assertIn("Noise rate", table)
        self.assertIn("100%", table)

    def test_undefined_metrics_render_as_a_dash_not_zero(self):
        self.assertIn("n/a", summary_table([("empty", Scores())]))

    def test_the_report_names_what_was_missed(self):
        scores = Scores()
        case = SimpleNamespace(name="off_by_one", is_clean=False, expected=[defect()])
        scores.cases.append(score_case(case, [], []))
        report = full_report("t", [("stub", scores)], primary=("stub", scores))
        self.assertIn("Missed defects", report)
        self.assertIn("off_by_one", report)


class RunLogTests(unittest.TestCase):
    def _report(self):
        report = MagicMock()
        report.results = [
            SimpleNamespace(
                provider="openai", model="gpt-5.6-luna", usage=Usage(10_000, 2_000), latency_s=3.0
            )
        ]
        report.all_findings = [finding(), finding(severity="nit", title="Nit")]
        report.budget = SimpleNamespace(
            posted=[finding()], over_budget=[], below_threshold=[], already_posted=[]
        )
        report.reviewed_paths = ["a.py"]
        report.ignored_paths = ["package-lock.json"]
        report.skipped_paths = []
        report.truncated = False
        report.parse_failed = False
        report.repaired = False
        report.incremental = True
        report.fully_reviewed = True
        report.panel = None
        return report

    def test_records_cost_coverage_and_counts(self):
        payload = build_runlog(self._report(), repository="o/r", pr_id=7)
        self.assertEqual(payload["model"], "gpt-5.6-luna")
        self.assertEqual(payload["tokens"], {"input": 10_000, "output": 2_000})
        self.assertEqual(payload["findings"]["posted"], 1)
        self.assertEqual(payload["findings"]["by_severity"]["major"], 1)
        self.assertEqual(payload["coverage"]["files_ignored"], 1)
        self.assertTrue(payload["incremental"])

    def test_estimates_cost_from_published_prices(self):
        # 10k in at $0.20/M + 2k out at $1.20/M
        self.assertAlmostEqual(estimate_cost("gpt-5.6-luna", 10_000, 2_000), 0.0044)

    def test_prices_a_gemini_model(self):
        self.assertAlmostEqual(estimate_cost("gemini-3.8-flash", 10_000, 2_000), 0.015)

    def test_an_unknown_model_yields_no_cost_rather_than_a_wrong_one(self):
        self.assertIsNone(estimate_cost("some-future-model", 1_000, 100))

    def test_never_records_source_code_or_rationale(self):
        """
        Run logs are uploaded as build artifacts. Titles are already public in
        the pull request; the code under review may not be.
        """
        payload = json.dumps(build_runlog(self._report()))
        self.assertIn("SQLi", payload)
        self.assertNotIn("Because.", payload)
        self.assertNotIn("rationale", payload)

    def test_never_records_the_api_key(self):
        payload = json.dumps(build_runlog(self._report()))
        for secret_ish in ("api_key", "sk-", "token\"", "Authorization"):
            self.assertNotIn(secret_ish, payload)


if __name__ == "__main__":
    unittest.main()
