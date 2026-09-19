"""
Spending the reviewer's attention.

This is the idea the whole tool is organised around. Writing code got cheap;
reviewing it did not. The scarce resource is a human's attention, and a bot
that posts forty comments does not add forty units of value — it spends forty
units of someone's attention and usually returns less than the five best
comments would have.

So the bot is given a budget and made to choose. What it suppresses is counted
and reported, never silently discarded: a reviewer who knows twelve minor
findings were held back can ask for them. A reviewer who was never told has
been quietly lied to about coverage.
"""

import logging
from dataclasses import dataclass, field

from findings import SEVERITIES, SEVERITY_RANK, Finding

logger = logging.getLogger(__name__)

DEFAULT_MAX_COMMENTS = 5
DEFAULT_MIN_SEVERITY = "nit"
DEFAULT_MIN_CONFIDENCE = 0.0


@dataclass
class BudgetOutcome:
    """What survived the budget, and everything that did not."""

    posted: list[Finding] = field(default_factory=list)
    below_threshold: list[Finding] = field(default_factory=list)
    over_budget: list[Finding] = field(default_factory=list)
    already_posted: list[Finding] = field(default_factory=list)

    @property
    def suppressed(self) -> list[Finding]:
        return self.below_threshold + self.over_budget

    @property
    def considered(self) -> int:
        return (
            len(self.posted)
            + len(self.below_threshold)
            + len(self.over_budget)
            + len(self.already_posted)
        )

    def counts_by_severity(self, findings=None) -> dict[str, int]:
        counts = {}
        for finding in self.posted if findings is None else findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        # Report in severity order rather than insertion order.
        return {name: counts[name] for name in SEVERITIES if name in counts}


def priority(finding: Finding) -> float:
    """
    Severity weighted by confidence, higher is more worth saying.

    Severity dominates: a blocker the model is half sure about still outranks a
    nit it is certain of, because the cost of missing the first is far higher
    than the cost of missing the second. Confidence then orders within a
    severity, which is where it does useful work — it is a comparative signal,
    not a calibrated probability, and treating it as one would be overreach.
    """
    weight = len(SEVERITIES) - SEVERITY_RANK.get(finding.severity, len(SEVERITIES))
    return weight * 10 + finding.confidence


def apply_budget(
    findings: list[Finding],
    *,
    max_comments: int = DEFAULT_MAX_COMMENTS,
    min_severity: str = DEFAULT_MIN_SEVERITY,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    already_posted_keys: set[str] | None = None,
) -> BudgetOutcome:
    """
    Choose which findings to post.

    Order of operations matters. Findings already posted in an earlier run are
    removed first, so a repeat finding does not consume budget that a new one
    could use. Thresholds come next, then ranking, then the budget itself.
    """
    outcome = BudgetOutcome()
    already_posted_keys = already_posted_keys or set()

    threshold_rank = SEVERITY_RANK.get(min_severity, SEVERITY_RANK[DEFAULT_MIN_SEVERITY])
    survivors = []

    for finding in findings:
        if fingerprint(finding) in already_posted_keys:
            outcome.already_posted.append(finding)
        elif SEVERITY_RANK.get(finding.severity, 99) > threshold_rank:
            outcome.below_threshold.append(finding)
        elif finding.confidence < min_confidence:
            outcome.below_threshold.append(finding)
        else:
            survivors.append(finding)

    survivors.sort(key=priority, reverse=True)

    if max_comments is not None and max_comments >= 0:
        outcome.posted = survivors[:max_comments]
        outcome.over_budget = survivors[max_comments:]
    else:
        outcome.posted = survivors

    logger.info(
        "Budget: %d posted, %d over budget, %d below threshold, %d already posted",
        len(outcome.posted),
        len(outcome.over_budget),
        len(outcome.below_threshold),
        len(outcome.already_posted),
    )
    return outcome


def fingerprint(finding: Finding) -> str:
    """
    A stable identity for a finding across runs.

    Deliberately not the line number: a later push that adds an import above
    shifts every line below it, and re-posting the same comment because the
    file moved down three lines is exactly the noise this phase exists to
    remove. File plus category plus a normalised title survives that, while
    still telling two different problems in one file apart.
    """
    title = " ".join(finding.title.lower().split())
    return f"{finding.file}:{finding.category}:{title}"


def risk_map(findings: list[Finding], limit: int = 5) -> list[tuple[str, float, str]]:
    """
    Files ranked by risk, with the reason.

    "Where to look first" is the single most useful thing a summary can give a
    reviewer who has ten minutes, and it is worth reporting even for findings
    that did not make the comment budget.
    """
    by_file: dict[str, list[Finding]] = {}
    for finding in findings:
        by_file.setdefault(finding.file, []).append(finding)

    ranked = []
    for path, file_findings in by_file.items():
        score = sum(priority(f) for f in file_findings)
        worst = min(file_findings, key=lambda f: f.rank)
        if len(file_findings) == 1:
            reason = f"{worst.severity}: {worst.title}"
        else:
            reason = f"{len(file_findings)} findings, worst is {worst.severity}: {worst.title}"
        ranked.append((path, score, reason))

    ranked.sort(key=lambda row: row[1], reverse=True)
    return ranked[:limit]
