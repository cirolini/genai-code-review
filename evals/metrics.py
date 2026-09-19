"""
Scoring a run against the eval set.

The metric that matters most for this project is not recall. A reviewer can
live with a bot that misses something; they stop reading a bot that wastes
their time. So noise rate — comments on diffs where the right answer was
silence — is reported alongside precision and recall rather than buried.
"""

from dataclasses import dataclass, field

from evals.cases import matches


@dataclass
class CaseResult:
    name: str
    is_clean: bool
    found: list = field(default_factory=list)
    missed: list = field(default_factory=list)
    spurious: list = field(default_factory=list)
    posted_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float | None = None
    error: str | None = None


@dataclass
class Scores:
    cases: list = field(default_factory=list)

    @property
    def true_positives(self) -> int:
        return sum(len(c.found) for c in self.cases)

    @property
    def false_negatives(self) -> int:
        return sum(len(c.missed) for c in self.cases)

    @property
    def false_positives(self) -> int:
        return sum(len(c.spurious) for c in self.cases)

    @property
    def precision(self) -> float | None:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else None

    @property
    def recall(self) -> float | None:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if not p or not r:
            return None
        return 2 * p * r / (p + r)

    @property
    def noise_rate(self) -> float | None:
        """
        Share of clean diffs that drew at least one comment.

        A bot that comments on a pure rename is teaching the reviewer to skim
        past it, which costs more than the comment was ever worth.
        """
        clean = [c for c in self.cases if c.is_clean]
        if not clean:
            return None
        return sum(1 for c in clean if c.posted_count) / len(clean)

    @property
    def comments_per_clean_diff(self) -> float | None:
        clean = [c for c in self.cases if c.is_clean]
        if not clean:
            return None
        return sum(c.posted_count for c in clean) / len(clean)

    @property
    def total_cost(self) -> float | None:
        costs = [c.cost_usd for c in self.cases if c.cost_usd is not None]
        return round(sum(costs), 4) if costs else None

    @property
    def cost_per_pr(self) -> float | None:
        total = self.total_cost
        return round(total / len(self.cases), 5) if total is not None and self.cases else None

    @property
    def mean_latency(self) -> float | None:
        if not self.cases:
            return None
        return round(sum(c.latency_s for c in self.cases) / len(self.cases), 2)

    @property
    def errors(self) -> int:
        return sum(1 for c in self.cases if c.error)


def score_case(case, findings, posted, usage_in=0, usage_out=0, latency=0.0, cost=None):
    """
    Compare one case's findings against its seeded defects.

    `findings` is everything the reviewer produced; `posted` is what survived
    the comment budget. Recall is measured against `findings` — did the model
    see it at all — while noise is measured against `posted`, since that is
    what actually reaches the human.
    """
    result = CaseResult(
        name=case.name,
        is_clean=case.is_clean,
        posted_count=len(posted),
        input_tokens=usage_in,
        output_tokens=usage_out,
        latency_s=latency,
        cost_usd=cost,
    )

    unmatched = list(findings)
    for defect in case.expected:
        hit = next((f for f in unmatched if matches(f, defect)), None)
        if hit is None:
            result.missed.append(defect)
        else:
            unmatched.remove(hit)
            result.found.append((defect, hit))

    result.spurious = unmatched
    return result
