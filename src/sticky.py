"""
The sticky summary comment, and the state it carries.

One comment per pull request, edited in place on every push instead of a new
one each time. v2 added a fresh comment on every push, so a pull request with
eight pushes accumulated eight stale reviews and eight notifications.

The comment is also where this action keeps its state. There is no database
and no external service, so the last reviewed SHA and the fingerprints of
findings already posted live in an HTML comment inside the body — invisible in
rendered Markdown, durable, and readable by the next run with one API call.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# Identifies our comment among everything else on the pull request.
MARKER = "<!-- genai-code-review:state"
MARKER_END = "-->"

_STATE_RE = re.compile(
    re.escape(MARKER) + r"\s*(?P<json>\{.*?\})\s*" + re.escape(MARKER_END),
    re.DOTALL,
)

STATE_VERSION = 1


def build_state(
    *,
    last_reviewed_sha: str | None,
    posted_fingerprints,
    suppressed_count: int = 0,
) -> dict:
    return {
        "version": STATE_VERSION,
        "last_reviewed_sha": last_reviewed_sha,
        "posted": sorted(set(posted_fingerprints)),
        "suppressed_count": suppressed_count,
    }


def render_state(state: dict) -> str:
    """Serialise state into an HTML comment, invisible in the rendered body."""
    return f"{MARKER}\n{json.dumps(state, sort_keys=True)}\n{MARKER_END}"


def parse_state(body: str | None) -> dict | None:
    """
    Read state back out of a comment body.

    Returns None for anything unreadable rather than raising. State that cannot
    be parsed should cost a duplicated comment, not a failed run — and a body
    edited by hand is a thing that happens.
    """
    if not body:
        return None
    match = _STATE_RE.search(body)
    if not match:
        return None
    try:
        state = json.loads(match.group("json"))
    except json.JSONDecodeError:
        logger.warning("Sticky comment state was not valid JSON; treating as a first run")
        return None

    if not isinstance(state, dict):
        return None
    if state.get("version") != STATE_VERSION:
        logger.info(
            "Sticky comment state is version %s, expected %s; treating as a first run",
            state.get("version"),
            STATE_VERSION,
        )
        return None
    return state


def is_ours(body: str | None) -> bool:
    return bool(body) and MARKER in body


def find_sticky_comment(github_client, pr_id):
    """
    The action's own comment on this pull request, if it has one.

    Returns None on any API failure: losing the sticky comment means posting a
    new one, which is a small cost, whereas failing the run over it is not.
    """
    try:
        for comment in github_client.get_pr_comments(pr_id):
            if is_ours(getattr(comment, "body", None)):
                return comment
    except Exception:
        logger.exception("Could not read existing comments; will post a new summary")
    return None


def upsert(github_client, pr_id, body: str, state: dict):
    """
    Create or update the single summary comment.

    Returns the comment. Editing in place is what stops a pull request
    accumulating one summary per push.
    """
    full_body = f"{body}\n\n{render_state(state)}"
    existing = find_sticky_comment(github_client, pr_id)

    if existing is None:
        logger.info("Posting a new summary comment")
        return github_client.post_comment(pr_id, full_body)

    try:
        existing.edit(full_body)
        logger.info("Updated the existing summary comment")
        return existing
    except Exception:
        logger.exception("Could not edit the summary comment; posting a new one")
        return github_client.post_comment(pr_id, full_body)


def previous_run(github_client, pr_id) -> dict:
    """State from the last run, or an empty state if this is the first."""
    comment = find_sticky_comment(github_client, pr_id)
    state = parse_state(getattr(comment, "body", None)) if comment else None
    return state or build_state(last_reviewed_sha=None, posted_fingerprints=[])
