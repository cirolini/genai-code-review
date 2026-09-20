"""
Acceptance signal: what reviewers actually did with the bot's comments.

The eval set measures the bot against seeded defects it was built to find.
That is a laboratory number. This reads the other end — a repository where the
action has been running — and reports what happened to the comments after they
were posted: reactions, replies, and whether the thread was resolved.

Two things this deliberately does not do.

It does not collapse the signals into one "accuracy" figure. A resolved thread
means the conversation ended, not that the finding was right: a reviewer
resolves a thread when they fix the problem *and* when they decide the bot was
wrong. Reported separately, the two signals are informative; averaged together
they are a number with no meaning.

It does not write anything. It reads a repository the action has run on, so
the only credential it needs is a read token.

Usage:

    python -m evals.feedback --repo owner/name --token "$GITHUB_TOKEN"
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import requests

API_ROOT = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")

# The header of every inline comment this action posts, from
# review_run._inline_comment: "**major · bug** — Off-by-one in the retry loop".
_HEADER_RE = re.compile(r"^\*\*(?P<severity>\w+) · (?P<category>\w+)\*\* — (?P<title>.+)$")

# Its footer: "<sub>confidence 80%</sub>". Present on every inline comment and
# on nothing else, which is what makes a comment identifiable as ours even if
# it was posted under a different bot account.
_CONFIDENCE_RE = re.compile(r"<sub>confidence (?P<pct>\d+)%</sub>")

POSITIVE_REACTIONS = ("+1", "heart", "hooray", "rocket")
NEGATIVE_REACTIONS = ("-1", "confused")


@dataclass
class Comment:
    """One inline comment this action posted, with what happened to it."""

    id: int
    pull_number: int
    created_at: str
    severity: str
    category: str
    confidence: float | None
    positive: int = 0
    negative: int = 0
    replies: int = 0
    resolved: bool | None = None

    @property
    def month(self) -> str:
        return self.created_at[:7]


@dataclass
class Summary:
    comments: list = field(default_factory=list)
    threads_known: bool = False

    @property
    def total(self) -> int:
        return len(self.comments)

    def _rate(self, predicate) -> float | None:
        if not self.comments:
            return None
        return sum(1 for c in self.comments if predicate(c)) / len(self.comments)

    @property
    def endorsed_rate(self) -> float | None:
        return self._rate(lambda c: c.positive > 0)

    @property
    def rejected_rate(self) -> float | None:
        return self._rate(lambda c: c.negative > 0)

    @property
    def replied_rate(self) -> float | None:
        return self._rate(lambda c: c.replies > 0)

    @property
    def resolved_rate(self) -> float | None:
        if not self.threads_known:
            return None
        return self._rate(lambda c: c.resolved is True)

    @property
    def ignored_rate(self) -> float | None:
        """
        Neither reacted to, replied to, nor resolved.

        The most common outcome, and the one worth watching: a comment nobody
        engaged with cost the reviewer attention and returned nothing.
        """

        def untouched(c):
            return c.positive == 0 and c.negative == 0 and c.replies == 0 and not c.resolved

        return self._rate(untouched)

    def group(self, key):
        """Sub-summaries by an attribute, preserving `threads_known`."""
        buckets = defaultdict(list)
        for comment in self.comments:
            buckets[key(comment)].append(comment)
        return {
            name: Summary(comments=group, threads_known=self.threads_known)
            for name, group in sorted(buckets.items())
        }


def parse_comment(body: str) -> dict | None:
    """
    Recognise an inline comment posted by this action, or return None.

    Identification is by shape, not by author: the severity/category header
    plus the confidence footer. An author filter is applied before this, but on
    its own it is not enough — the same bot account posts the sticky summary
    and, in most repositories, a lot of unrelated comments.
    """
    if not body:
        return None
    confidence_match = _CONFIDENCE_RE.search(body)
    header_match = _HEADER_RE.match(body.splitlines()[0].strip()) if body.strip() else None
    if not header_match or not confidence_match:
        return None
    return {
        "severity": header_match.group("severity"),
        "category": header_match.group("category"),
        "confidence": int(confidence_match.group("pct")) / 100,
    }


def _pull_number(comment: dict) -> int:
    """
    The pull request a review comment belongs to.

    The repository-wide listing does not carry a pull number, only a
    `pull_request_url` ending in it.
    """
    url = comment.get("pull_request_url") or ""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def build_comments(raw_comments, *, author: str | None, resolved_ids=None) -> list:
    """Turn the API's review comments into `Comment` rows, dropping anything not ours."""
    resolved_ids = resolved_ids if resolved_ids is not None else {}
    reply_counts = Counter(
        c["in_reply_to_id"] for c in raw_comments if c.get("in_reply_to_id") is not None
    )

    rows = []
    for raw in raw_comments:
        if raw.get("in_reply_to_id") is not None:
            continue
        if author and (raw.get("user") or {}).get("login") != author:
            continue
        parsed = parse_comment(raw.get("body", ""))
        if parsed is None:
            continue
        reactions = raw.get("reactions") or {}
        rows.append(
            Comment(
                id=raw["id"],
                pull_number=_pull_number(raw),
                created_at=raw.get("created_at", ""),
                severity=parsed["severity"],
                category=parsed["category"],
                confidence=parsed["confidence"],
                positive=sum(reactions.get(name, 0) for name in POSITIVE_REACTIONS),
                negative=sum(reactions.get(name, 0) for name in NEGATIVE_REACTIONS),
                replies=reply_counts.get(raw["id"], 0),
                resolved=resolved_ids.get(raw["id"]),
            )
        )
    return rows


def _pct(value) -> str:
    return f"{value:.0%}" if value is not None else "n/a"


def render(summary: Summary, repo: str) -> str:
    """The report. Signals side by side, never averaged into one score."""
    if not summary.total:
        return (
            f"# Acceptance signal — {repo}\n\n"
            "No inline comments from this action were found. Either it has not "
            "run on this repository, or it ran in `files`/`patch` mode, which "
            "posts a summary comment rather than inline findings.\n"
        )

    resolved_note = (
        "" if summary.threads_known else " *(thread state unavailable — see below)*"
    )
    lines = [
        f"# Acceptance signal — {repo}",
        "",
        f"{summary.total} inline comment(s) from this action.",
        "",
        "| Signal | Share |",
        "|---|---|",
        f"| 👍 reaction | {_pct(summary.endorsed_rate)} |",
        f"| 👎 reaction | {_pct(summary.rejected_rate)} |",
        f"| Replied to | {_pct(summary.replied_rate)} |",
        f"| Thread resolved{resolved_note} | {_pct(summary.resolved_rate)} |",
        f"| No engagement at all | {_pct(summary.ignored_rate)} |",
        "",
        "A resolved thread is not agreement: reviewers resolve a thread both "
        "when they act on a finding and when they dismiss it. The row worth "
        "watching is the last one — comments nobody touched are attention "
        "spent for nothing.",
    ]

    grouped = (("By severity", lambda c: c.severity), ("By category", lambda c: c.category))
    for title, key in grouped:
        groups = summary.group(key)
        lines += [
            "",
            f"## {title}",
            "",
            "| | Comments | 👍 | 👎 | Resolved | Ignored |",
            "|---|---|---|---|---|---|",
        ]
        for name, group in groups.items():
            lines.append(
                f"| `{name}` | {group.total} | {_pct(group.endorsed_rate)} | "
                f"{_pct(group.rejected_rate)} | {_pct(group.resolved_rate)} | "
                f"{_pct(group.ignored_rate)} |"
            )

    months = summary.group(lambda c: c.month)
    if len(months) > 1:
        lines += [
            "",
            "## Over time",
            "",
            "| Month | Comments | 👍 | 👎 | Ignored |",
            "|---|---|---|---|---|",
        ]
        for name, group in months.items():
            lines.append(
                f"| {name} | {group.total} | {_pct(group.endorsed_rate)} | "
                f"{_pct(group.rejected_rate)} | {_pct(group.ignored_rate)} |"
            )

    if not summary.threads_known:
        lines += [
            "",
            "Thread resolution comes from the GraphQL API and was not "
            "available for this run, so that column is `n/a`. The token needs "
            "`repo` scope on a private repository, or `public_repo` on a "
            "public one.",
        ]

    return "\n".join(lines) + "\n"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_review_comments(repo: str, token: str, *, since: str | None = None, timeout=30) -> list:
    """Every review comment in the repository, newest page last."""
    comments = []
    url = f"{API_ROOT}/repos/{repo}/pulls/comments"
    params = {"per_page": 100, "sort": "created", "direction": "desc"}
    if since:
        params["since"] = since

    while url:
        response = requests.get(url, headers=_headers(token), params=params, timeout=timeout)
        response.raise_for_status()
        page = response.json()
        comments.extend(page)
        url = response.links.get("next", {}).get("url")
        params = None  # the next link already carries them
    return comments


# GitHub rejects a GraphQL query whose *possible* node count exceeds 500,000,
# counted from the page sizes alone — before a single node exists. Nesting
# three connections multiplies them, so the obvious 50 x 100 x 100 is refused
# outright on an empty repository. These three numbers are what keeps the query
# accepted; `possible_nodes` below is the arithmetic, and a test asserts it.
PULLS_PER_PAGE = 25
THREADS_PER_PULL = 50
COMMENTS_PER_THREAD = 50

GRAPHQL_NODE_LIMIT = 500_000

_THREADS_QUERY = f"""
query($owner: String!, $name: String!, $cursor: String) {{
  repository(owner: $owner, name: $name) {{
    pullRequests(first: {PULLS_PER_PAGE}, orderBy: {{field: UPDATED_AT, direction: DESC}},
                 after: $cursor) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        reviewThreads(first: {THREADS_PER_PULL}) {{
          nodes {{
            isResolved
            comments(first: {COMMENTS_PER_THREAD}) {{ nodes {{ databaseId }} }}
          }}
        }}
      }}
    }}
  }}
}}
"""


def possible_nodes() -> int:
    """
    GitHub's own node estimate for `_THREADS_QUERY`.

    Each parent connection multiplies the children it can hold, plus itself:
    pulls x (1 + threads x (1 + comments)).
    """
    return PULLS_PER_PAGE * (1 + THREADS_PER_PULL * (1 + COMMENTS_PER_THREAD))


def fetch_thread_resolution(repo: str, token: str, *, max_pages=10, timeout=30) -> dict:
    """
    Map comment id → whether its thread is resolved.

    Only the REST API lists comments repository-wide, and only GraphQL knows
    whether a thread was resolved, so this is a second pass rather than one
    query. A failure here is not fatal: the report prints `n/a` for resolution
    and says why.
    """
    owner, _, name = repo.partition("/")
    resolved = {}
    cursor = None

    for _ in range(max_pages):
        response = requests.post(
            f"{API_ROOT}/graphql",
            headers=_headers(token),
            json={
                "query": _THREADS_QUERY,
                "variables": {"owner": owner, "name": name, "cursor": cursor},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(payload["errors"][0].get("message", "GraphQL error"))

        pulls = payload["data"]["repository"]["pullRequests"]
        for pull in pulls["nodes"]:
            for thread in pull["reviewThreads"]["nodes"]:
                for comment in thread["comments"]["nodes"]:
                    resolved[comment["databaseId"]] = thread["isResolved"]

        if not pulls["pageInfo"]["hasNextPage"]:
            break
        cursor = pulls["pageInfo"]["endCursor"]

    return resolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Estimate acceptance of this action's review comments in a repository."
    )
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN"),
        help="GitHub token with read access (default: $GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--author",
        default="github-actions[bot]",
        help="Only count comments by this login; pass an empty string to count any author",
    )
    parser.add_argument("--since", default=None, help="ISO 8601 timestamp; only newer comments")
    parser.add_argument("--out", default=None, help="Write the Markdown report here")
    parser.add_argument("--json-out", default=None, help="Write the per-comment rows here")
    args = parser.parse_args(argv)

    if not args.token:
        print("A GitHub token is required: --token or $GITHUB_TOKEN.", file=sys.stderr)
        return 2

    raw = fetch_review_comments(args.repo, args.token, since=args.since)

    resolved_ids, threads_known = {}, True
    try:
        resolved_ids = fetch_thread_resolution(args.repo, args.token)
    except Exception as exc:  # reported in the output rather than being fatal
        print(f"Thread resolution unavailable: {exc}", file=sys.stderr)
        threads_known = False

    summary = Summary(
        comments=build_comments(raw, author=args.author or None, resolved_ids=resolved_ids),
        threads_known=threads_known,
    )
    report = render(summary, args.repo)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(report)
        print(f"Wrote {args.out}")
    else:
        print(report)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump([vars(c) for c in summary.comments], handle, indent=2, sort_keys=True)
        print(f"Wrote {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
