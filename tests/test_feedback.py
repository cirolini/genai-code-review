"""
Tests for the acceptance-signal reader.

Everything here runs against fixture payloads shaped like the GitHub API's.
No token, no network: the parts worth testing are the recognition of our own
comments among everybody else's and the arithmetic on top of them.
"""

import unittest

from evals.feedback import (
    GRAPHQL_NODE_LIMIT,
    Summary,
    build_comments,
    parse_comment,
    possible_nodes,
    render,
)

from findings import Finding
from review_run import _inline_comment


def bot_body(severity="major", category="bug", confidence=0.8, suggestion=None):
    """The real thing: built by the same function that posts it."""
    return _inline_comment(
        Finding(
            file="app/users.py",
            line_start=12,
            line_end=12,
            severity=severity,
            category=category,
            confidence=confidence,
            title="Off-by-one in the retry loop",
            rationale="The loop runs one iteration too many.",
            suggestion=suggestion,
        )
    )["body"]


def api_comment(
    comment_id=1,
    body=None,
    login="github-actions[bot]",
    reactions=None,
    in_reply_to=None,
    created_at="2026-09-01T10:00:00Z",
    pull_number=42,
):
    return {
        "id": comment_id,
        "body": bot_body() if body is None else body,
        "user": {"login": login},
        "reactions": reactions or {},
        "in_reply_to_id": in_reply_to,
        "created_at": created_at,
        "pull_request_url": f"https://api.github.com/repos/o/n/pulls/{pull_number}",
    }


class ParseCommentTests(unittest.TestCase):
    def test_recognises_a_comment_this_action_posted(self):
        parsed = parse_comment(bot_body(severity="blocker", category="security", confidence=0.65))
        self.assertEqual(parsed["severity"], "blocker")
        self.assertEqual(parsed["category"], "security")
        self.assertAlmostEqual(parsed["confidence"], 0.65)

    def test_recognises_one_carrying_a_suggestion_block(self):
        parsed = parse_comment(bot_body(suggestion="for i in range(n):"))
        self.assertEqual(parsed["category"], "bug")

    def test_ignores_a_human_comment(self):
        self.assertIsNone(parse_comment("**major · bug** — looks wrong to me"))

    def test_ignores_the_sticky_summary(self):
        body = "## Code review\n\nNothing worth flagging.\n\n<sub>gemini · `x` · 1.0s</sub>"
        self.assertIsNone(parse_comment(body))

    def test_ignores_empty_bodies(self):
        self.assertIsNone(parse_comment(""))
        self.assertIsNone(parse_comment(None))


class BuildCommentsTests(unittest.TestCase):
    def test_keeps_only_comments_by_the_named_author(self):
        raw = [
            api_comment(comment_id=1),
            api_comment(comment_id=2, login="someone-else"),
        ]
        rows = build_comments(raw, author="github-actions[bot]")
        self.assertEqual([r.id for r in rows], [1])

    def test_an_empty_author_counts_every_login(self):
        raw = [api_comment(comment_id=1), api_comment(comment_id=2, login="other-bot")]
        self.assertEqual(len(build_comments(raw, author=None)), 2)

    def test_replies_are_counted_not_listed(self):
        raw = [
            api_comment(comment_id=1),
            api_comment(comment_id=9, body="I disagree", login="human", in_reply_to=1),
        ]
        rows = build_comments(raw, author=None)
        self.assertEqual([r.id for r in rows], [1])
        self.assertEqual(rows[0].replies, 1)

    def test_reactions_are_summed_by_polarity(self):
        raw = [api_comment(reactions={"+1": 2, "rocket": 1, "-1": 1, "eyes": 5})]
        row = build_comments(raw, author=None)[0]
        self.assertEqual(row.positive, 3)
        self.assertEqual(row.negative, 1)

    def test_pull_number_comes_from_the_url(self):
        row = build_comments([api_comment(pull_number=77)], author=None)[0]
        self.assertEqual(row.pull_number, 77)

    def test_resolution_is_attached_by_comment_id(self):
        raw = [api_comment(comment_id=1), api_comment(comment_id=2)]
        rows = build_comments(raw, author=None, resolved_ids={1: True, 2: False})
        self.assertEqual([r.resolved for r in rows], [True, False])

    def test_unknown_resolution_stays_none(self):
        row = build_comments([api_comment(comment_id=1)], author=None, resolved_ids={})[0]
        self.assertIsNone(row.resolved)


class ThreadQueryTests(unittest.TestCase):
    """
    The node budget is checked before the query runs, not after.

    GitHub counts the nodes a query *could* return from the page sizes alone,
    so a nesting that is too wide is rejected on an empty repository — which is
    how the first version of this query failed: 50 pulls x 100 threads x 100
    comments is 505,050 possible nodes against a limit of 500,000.
    """

    def test_the_query_stays_inside_the_node_limit(self):
        self.assertLess(possible_nodes(), GRAPHQL_NODE_LIMIT)

    def test_the_rejected_nesting_would_still_be_caught(self):
        rejected = 50 * (1 + 100 * (1 + 100))
        self.assertGreater(rejected, GRAPHQL_NODE_LIMIT)


class SummaryTests(unittest.TestCase):
    def summary(self, raw, **kwargs):
        return Summary(comments=build_comments(raw, author=None), **kwargs)

    def test_rates_are_none_with_no_comments(self):
        empty = Summary()
        self.assertIsNone(empty.endorsed_rate)
        self.assertIsNone(empty.ignored_rate)

    def test_endorsement_and_rejection_count_comments_not_reactions(self):
        raw = [
            api_comment(comment_id=1, reactions={"+1": 4}),
            api_comment(comment_id=2, reactions={"-1": 1}),
            api_comment(comment_id=3),
            api_comment(comment_id=4),
        ]
        summary = self.summary(raw)
        self.assertAlmostEqual(summary.endorsed_rate, 0.25)
        self.assertAlmostEqual(summary.rejected_rate, 0.25)

    def test_ignored_means_no_signal_of_any_kind(self):
        raw = [
            api_comment(comment_id=1, reactions={"+1": 1}),
            api_comment(comment_id=2),
        ]
        rows = build_comments(raw, author=None, resolved_ids={2: False})
        self.assertAlmostEqual(Summary(comments=rows).ignored_rate, 0.5)

    def test_resolution_rate_is_none_until_threads_are_known(self):
        raw = [api_comment(comment_id=1)]
        rows = build_comments(raw, author=None, resolved_ids={1: True})
        self.assertIsNone(Summary(comments=rows).resolved_rate)
        self.assertAlmostEqual(Summary(comments=rows, threads_known=True).resolved_rate, 1.0)

    def test_grouping_splits_by_attribute_and_keeps_thread_state(self):
        raw = [
            api_comment(comment_id=1, body=bot_body(severity="blocker")),
            api_comment(comment_id=2, body=bot_body(severity="nit")),
            api_comment(comment_id=3, body=bot_body(severity="nit")),
        ]
        groups = self.summary(raw, threads_known=True).group(lambda c: c.severity)
        self.assertEqual(sorted(groups), ["blocker", "nit"])
        self.assertEqual(groups["nit"].total, 2)
        self.assertTrue(groups["nit"].threads_known)

    def test_month_comes_from_the_creation_date(self):
        raw = [api_comment(created_at="2026-07-14T09:00:00Z")]
        self.assertEqual(self.summary(raw).comments[0].month, "2026-07")


class RenderTests(unittest.TestCase):
    def test_says_so_when_nothing_was_found(self):
        report = render(Summary(), "o/n")
        self.assertIn("No inline comments", report)

    def test_reports_each_signal_separately(self):
        raw = [
            api_comment(comment_id=1, reactions={"+1": 1}, body=bot_body(severity="blocker")),
            api_comment(comment_id=2, body=bot_body(severity="nit", category="style")),
        ]
        rows = build_comments(raw, author=None, resolved_ids={1: True, 2: False})
        report = render(Summary(comments=rows, threads_known=True), "o/n")

        self.assertIn("👍 reaction | 50%", report)
        self.assertIn("No engagement at all | 50%", report)
        self.assertIn("`blocker`", report)
        self.assertIn("`style`", report)
        self.assertNotIn("n/a", report)

    def test_explains_a_missing_thread_state_instead_of_hiding_it(self):
        rows = build_comments([api_comment()], author=None)
        report = render(Summary(comments=rows, threads_known=False), "o/n")
        self.assertIn("n/a", report)
        self.assertIn("GraphQL", report)

    def test_over_time_appears_only_with_more_than_one_month(self):
        one_month = build_comments([api_comment(created_at="2026-09-01T00:00:00Z")], author=None)
        self.assertNotIn("## Over time", render(Summary(comments=one_month), "o/n"))

        two_months = build_comments(
            [
                api_comment(comment_id=1, created_at="2026-08-01T00:00:00Z"),
                api_comment(comment_id=2, created_at="2026-09-01T00:00:00Z"),
            ],
            author=None,
        )
        self.assertIn("## Over time", render(Summary(comments=two_months), "o/n"))


if __name__ == "__main__":
    unittest.main()
