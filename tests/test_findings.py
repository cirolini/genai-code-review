"""
Tests for schema validation of model output.

The point of this module is that a model that returns nonsense must not crash
the action on somebody's pull request, and must not silently drop findings that
were fine.
"""

import json
import unittest

from findings import (
    CATEGORIES,
    FINDINGS_SCHEMA,
    SEVERITIES,
    Finding,
    InvalidFindings,
    parse_findings,
)


def valid(**overrides):
    finding = {
        "file": "app/auth.py",
        "line_start": 10,
        "line_end": 10,
        "severity": "blocker",
        "category": "security",
        "confidence": 0.9,
        "title": "SQL injection",
        "rationale": "Username is interpolated into the query.",
    }
    finding.update(overrides)
    return finding


def payload(*items):
    return json.dumps({"findings": list(items)})


class HappyPathTests(unittest.TestCase):
    def test_parses_a_well_formed_response(self):
        [finding] = parse_findings(payload(valid()))
        self.assertEqual(finding.file, "app/auth.py")
        self.assertEqual(finding.severity, "blocker")
        self.assertEqual(finding.confidence, 0.9)
        self.assertIsNone(finding.suggestion)

    def test_accepts_an_empty_findings_array(self):
        """'Nothing to report' is a valid and useful answer."""
        self.assertEqual(parse_findings(payload()), [])

    def test_accepts_a_bare_array(self):
        self.assertEqual(len(parse_findings(json.dumps([valid()]))), 1)

    def test_extracts_json_from_a_code_fence(self):
        self.assertEqual(len(parse_findings(f"Here you go:\n```json\n{payload(valid())}\n```")), 1)

    def test_extracts_json_surrounded_by_prose(self):
        raw = f"I found one issue. {payload(valid())} Hope it helps."
        self.assertEqual(len(parse_findings(raw)), 1)


class ValidationTests(unittest.TestCase):
    def test_rejects_an_unknown_severity(self):
        with self.assertRaises(InvalidFindings) as ctx:
            parse_findings(payload(valid(severity="catastrophic")))
        self.assertIn("severity", ctx.exception.repair_hint())

    def test_rejects_an_unknown_category(self):
        with self.assertRaises(InvalidFindings):
            parse_findings(payload(valid(category="vibes")))

    def test_severity_and_category_are_case_insensitive(self):
        [finding] = parse_findings(payload(valid(severity="BLOCKER", category="Security")))
        self.assertEqual(finding.severity, "blocker")
        self.assertEqual(finding.category, "security")

    def test_rejects_confidence_outside_zero_to_one(self):
        for bad in (1.5, -0.1, 42):
            with self.subTest(confidence=bad):
                with self.assertRaises(InvalidFindings):
                    parse_findings(payload(valid(confidence=bad)))

    def test_accepts_confidence_as_a_numeric_string(self):
        [finding] = parse_findings(payload(valid(confidence="0.4")))
        self.assertEqual(finding.confidence, 0.4)

    def test_rejects_a_boolean_line_number(self):
        """bool is an int subclass, so this has to be excluded deliberately."""
        with self.assertRaises(InvalidFindings):
            parse_findings(payload(valid(line_start=True)))

    def test_rejects_a_line_number_below_one(self):
        with self.assertRaises(InvalidFindings):
            parse_findings(payload(valid(line_start=0)))

    def test_swaps_a_reversed_line_range(self):
        [finding] = parse_findings(payload(valid(line_start=20, line_end=10)))
        self.assertEqual((finding.line_start, finding.line_end), (10, 20))

    def test_defaults_line_end_to_line_start(self):
        item = valid()
        del item["line_end"]
        [finding] = parse_findings(payload(item))
        self.assertEqual(finding.line_end, finding.line_start)

    def test_truncates_an_overlong_title(self):
        [finding] = parse_findings(payload(valid(title="x" * 400)))
        self.assertLessEqual(len(finding.title), 120)

    def test_rejects_a_missing_rationale(self):
        item = valid()
        del item["rationale"]
        with self.assertRaises(InvalidFindings):
            parse_findings(payload(item))


class PartialFailureTests(unittest.TestCase):
    def test_keeps_the_good_findings_and_drops_the_bad_one(self):
        """Losing four sound findings because a fifth was malformed serves nobody."""
        findings = parse_findings(
            payload(valid(title="one"), valid(severity="nonsense"), valid(title="three"))
        )
        self.assertEqual([f.title for f in findings], ["one", "three"])

    def test_raises_only_when_nothing_survives(self):
        with self.assertRaises(InvalidFindings):
            parse_findings(payload(valid(severity="nonsense")))


class MalformedResponseTests(unittest.TestCase):
    def test_empty_response(self):
        for raw in ("", "   ", "\n"):
            with self.subTest(raw=repr(raw)):
                with self.assertRaises(InvalidFindings):
                    parse_findings(raw)

    def test_prose_only_response(self):
        with self.assertRaises(InvalidFindings) as ctx:
            parse_findings("The code looks fine to me, no issues found.")
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_json_without_a_findings_key(self):
        with self.assertRaises(InvalidFindings) as ctx:
            parse_findings(json.dumps({"issues": []}))
        self.assertIn("findings", str(ctx.exception))

    def test_repair_hint_is_specific_enough_to_act_on(self):
        with self.assertRaises(InvalidFindings) as ctx:
            parse_findings(payload(valid(severity="nope", confidence=9)))
        hint = ctx.exception.repair_hint()
        self.assertIn("severity", hint)
        self.assertIn("confidence", hint)


class SchemaConsistencyTests(unittest.TestCase):
    """The schema sent to providers must match what the validator accepts."""

    def test_enums_match_the_validator(self):
        properties = FINDINGS_SCHEMA["properties"]["findings"]["items"]["properties"]
        self.assertEqual(tuple(properties["severity"]["enum"]), SEVERITIES)
        self.assertEqual(tuple(properties["category"]["enum"]), CATEGORIES)

    def test_required_fields_match_the_dataclass(self):
        required = set(FINDINGS_SCHEMA["properties"]["findings"]["items"]["required"])
        fields = set(Finding.__dataclass_fields__)
        self.assertTrue(required <= fields)
        # `relocated` is set by placement, never by the model, so it is not
        # in the schema at all.
        self.assertEqual(fields - required, {"suggestion", "relocated"})
        item = FINDINGS_SCHEMA["properties"]["findings"]["items"]
        self.assertNotIn("relocated", item["properties"])


class RankingTests(unittest.TestCase):
    def test_ranks_by_severity_then_confidence(self):
        blocker_low = Finding("f", 1, 1, "blocker", "bug", 0.3, "t", "r")
        blocker_high = Finding("f", 1, 1, "blocker", "bug", 0.9, "t", "r")
        nit = Finding("f", 1, 1, "nit", "style", 1.0, "t", "r")
        self.assertLess(blocker_high.rank, blocker_low.rank)
        self.assertLess(blocker_low.rank, nit.rank)


if __name__ == "__main__":
    unittest.main()
