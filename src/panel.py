"""
Panel mode: run two providers and merge what they found.

The hypothesis is that agreement between independent models is evidence a
finding is real, and disagreement is evidence it is taste. If that holds, a
panel lets the comment budget be spent on findings that survived a second
opinion rather than on whichever ones one model happened to rank highest.

It is an experiment, and it is honest about the price: two providers means
roughly twice the tokens and twice the latency for one review. Phase 4 measures
whether that buys enough precision to be worth it. Until those numbers exist,
this is off by default.
"""

import logging
from dataclasses import dataclass, field

from budget import fingerprint
from findings import Finding

logger = logging.getLogger(__name__)

# Applied to a finding only one member of the panel reported. Chosen to demote
# rather than eliminate: a single model spotting a real blocker the other
# missed is a case worth keeping, just ranked below corroborated findings.
SOLO_CONFIDENCE_FACTOR = 0.7

# Applied to a finding both members reported, capped at 1.0.
AGREED_CONFIDENCE_FACTOR = 1.15


@dataclass
class PanelOutcome:
    findings: list[Finding] = field(default_factory=list)
    agreed_count: int = 0
    solo_count: int = 0
    members: list[str] = field(default_factory=list)
    failed_members: list[tuple[str, str]] = field(default_factory=list)

    @property
    def agreement_rate(self) -> float | None:
        """
        Share of distinct findings that both members reported.

        None when there was nothing to agree about — reporting 0% agreement on
        an empty review would be a misleading number, not a neutral one.
        """
        total = self.agreed_count + self.solo_count
        return self.agreed_count / total if total else None


def merge(results: list[tuple[str, list[Finding]]]) -> PanelOutcome:
    """
    Combine findings from several panel members.

    Findings are matched by the same fingerprint the incremental review uses —
    file, category and normalised title — because two models describing one
    defect rarely pick the same line or the same wording, but do land on the
    same file and the same kind of problem.
    """
    outcome = PanelOutcome(members=[name for name, _ in results])

    if len(results) == 1:
        outcome.findings = results[0][1]
        outcome.solo_count = len(outcome.findings)
        return outcome

    by_key: dict[str, list[tuple[str, Finding]]] = {}
    for member, findings in results:
        for finding in findings:
            by_key.setdefault(fingerprint(finding), []).append((member, finding))

    merged: list[Finding] = []
    for entries in by_key.values():
        reporters = {member for member, _ in entries}
        # Keep the most severe, most confident version of the finding.
        best = min((finding for _, finding in entries), key=lambda f: f.rank)

        if len(reporters) > 1:
            best.confidence = min(1.0, best.confidence * AGREED_CONFIDENCE_FACTOR)
            reported_by = ", ".join(sorted(reporters))
            best.rationale = (
                f"{best.rationale}\n\nReported independently by: {reported_by}."
            )
            outcome.agreed_count += 1
        else:
            best.confidence = round(best.confidence * SOLO_CONFIDENCE_FACTOR, 4)
            outcome.solo_count += 1

        merged.append(best)

    outcome.findings = merged
    logger.info(
        "Panel merged %d finding(s): %d agreed, %d from one member",
        len(merged),
        outcome.agreed_count,
        outcome.solo_count,
    )
    return outcome


def parse_panel(raw: str | None) -> list[str]:
    """
    Read the `panel` input: a comma- or newline-separated list of providers.

    Empty means no panel, which is the default.
    """
    if not raw or not raw.strip():
        return []
    members = []
    for part in raw.replace("\n", ",").split(","):
        name = part.strip().lower()
        if name and name not in members:
            members.append(name)
    return members
