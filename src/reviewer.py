"""
Runs a review and decides what can actually be commented on.

Two jobs: get valid findings out of the model (with one repair attempt), and
reconcile those findings against the diff, because a finding pointing at a line
GitHub will not accept takes the entire review request down with it.
"""

import logging
from dataclasses import dataclass, field

from diff import ParsedDiff
from findings import Finding, InvalidFindings, parse_findings
from prompts import build_repair_prompt, build_review_prompt
from providers.base import ReviewResult

logger = logging.getLogger(__name__)

# How far a finding's line may be from the nearest line in the diff before it is
# dropped rather than snapped. Small on purpose: a model that is twenty lines
# out is not describing the line it thinks it is.
MAX_LINE_SNAP_DISTANCE = 3


@dataclass
class ReviewOutcome:
    """Everything one review produced, including what it could not use."""

    findings: list[Finding] = field(default_factory=list)
    unplaceable: list[tuple[Finding, str]] = field(default_factory=list)
    repaired: bool = False
    parse_failed: bool = False
    raw_text: str = ""
    result: ReviewResult | None = None

    @property
    def usage(self):
        return self.result.usage if self.result else None


def run_review(
    provider,
    diff_text: str,
    parsed: ParsedDiff,
    *,
    language: str = "en",
    custom_prompt: str | None = None,
    schema: dict | None = None,
) -> ReviewOutcome:
    """
    Ask the provider for findings and place them on the diff.

    Never raises for bad model output: a malformed response degrades to zero
    findings with `parse_failed` set, so the caller can say so in the summary
    instead of the action crashing on somebody's pull request.
    """
    prompt = build_review_prompt(diff_text, language=language, custom_prompt=custom_prompt)
    result = provider.review(prompt, schema)

    outcome = ReviewOutcome(raw_text=result.text, result=result)

    try:
        findings = parse_findings(result.text)
    except InvalidFindings as first_error:
        logger.warning("Model output did not validate: %s", first_error)
        findings, outcome.repaired = _attempt_repair(provider, result.text, first_error, schema)
        if findings is None:
            outcome.parse_failed = True
            return outcome

    placed, unplaceable = place_findings(findings, parsed)
    outcome.findings = placed
    outcome.unplaceable = unplaceable
    return outcome


def _attempt_repair(provider, previous: str, error: InvalidFindings, schema):
    """One repair attempt. Not two: a model that fails twice is not converging."""
    try:
        repair = provider.review(build_repair_prompt(previous, error.repair_hint()), schema)
        return parse_findings(repair.text), True
    except InvalidFindings as second_error:
        logger.error("Repair attempt also failed to validate: %s", second_error)
        return None, True
    except Exception:
        logger.exception("Repair attempt failed")
        return None, True


def place_findings(
    findings: list[Finding], parsed: ParsedDiff
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    """
    Keep the findings that can be attached to a line in the diff.

    GitHub rejects a review comment on a line outside the diff, and it rejects
    the whole review rather than the one comment — so this filter is what keeps
    a single confused finding from silencing the entire review.

    A finding that is within a few lines of a real diff line is snapped to it.
    Models miscount by one or two often enough that discarding those would lose
    real defects; being twenty lines out means something else is wrong.
    """
    placed: list[Finding] = []
    rejected: list[tuple[Finding, str]] = []

    for finding in findings:
        diff_file = parsed.get(finding.file)
        if diff_file is None:
            rejected.append((finding, f"`{finding.file}` is not in this diff"))
            continue
        if diff_file.is_binary or diff_file.is_deleted:
            rejected.append((finding, f"`{finding.file}` is binary or deleted"))
            continue

        if diff_file.can_comment_on(finding.line_start):
            placed.append(_clamp_range(finding, diff_file))
            continue

        nearest = diff_file.nearest_commentable_line(finding.line_start)
        if nearest is None:
            rejected.append((finding, f"`{finding.file}` has no commentable lines"))
            continue

        distance = abs(nearest - finding.line_start)
        if distance > MAX_LINE_SNAP_DISTANCE:
            rejected.append(
                (
                    finding,
                    f"line {finding.line_start} is not in the diff "
                    f"(nearest changed line is {nearest})",
                )
            )
            continue

        logger.info(
            "Snapping %s:%d to %d (%d line(s) away)",
            finding.file,
            finding.line_start,
            nearest,
            distance,
        )
        span = finding.line_end - finding.line_start
        finding.line_start = nearest
        finding.line_end = nearest + span
        placed.append(_clamp_range(finding, diff_file))

    return placed, rejected


def _clamp_range(finding: Finding, diff_file) -> Finding:
    """
    Shrink a multi-line finding to lines that are actually in the diff.

    A range that starts inside the diff and runs past the end of a hunk is
    rejected by GitHub just as an out-of-range single line is.
    """
    if finding.line_end == finding.line_start:
        return finding

    end = finding.line_end
    while end > finding.line_start and not diff_file.can_comment_on(end):
        end -= 1
    finding.line_end = end
    return finding


def rank(findings: list[Finding]) -> list[Finding]:
    """Most serious first, most confident first within a severity."""
    return sorted(findings, key=lambda f: f.rank)
