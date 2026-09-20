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
    # The same two counts, restricted to the findings that survived the budget
    # and actually reached the pull request.
    posted_found: int = 0
    posted_spurious: int = 0
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
    def posted_true_positives(self) -> int:
        return sum(c.posted_found for c in self.cases)

    @property
    def posted_false_positives(self) -> int:
        return sum(c.posted_spurious for c in self.cases)

    @property
    def posted_precision(self) -> float | None:
        """
        Of the comments the reviewer actually received, how many were real.

        This is the number the comment budget is trying to move. Precision over
        all findings says how good the model is; this says how good the review
        was.
        """
        denominator = self.posted_true_positives + self.posted_false_positives
        return self.posted_true_positives / denominator if denominator else None

    @property
    def posted_recall(self) -> float | None:
        """
        Seeded defects that reached the reviewer.

        Expected to sit below `recall` whenever the budget binds: that gap is
        the cost of the budget, and it is the thing worth arguing about.
        """
        denominator = self.true_positives + self.false_negatives
        return self.posted_true_positives / denominator if denominator else None

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


def _match_defects(expected, findings):
    """
    Pair seeded defects with the findings that hit them.

    Returns (pairs, missed defects, findings that matched nothing).
    """
    unmatched = list(findings)
    pairs, missed = [], []
    for defect in expected:
        hit = next((f for f in unmatched if matches(f, defect)), None)
        if hit is None:
            missed.append(defect)
        else:
            unmatched.remove(hit)
            pairs.append((defect, hit))
    return pairs, missed, unmatched


def score_case(case, findings, posted, usage_in=0, usage_out=0, latency=0.0, cost=None):
    """
    Compare one case's findings against its seeded defects, twice.

    `findings` is everything the reviewer produced; `posted` is what survived
    the comment budget. Both are scored, because they answer different
    questions and the gap between them is the budget's entire effect:

    - against `findings`: did the model see the defect at all?
    - against `posted`: did the *reviewer* see it?

    Scoring only the first, which is what this did until the budget had
    fixtures large enough to bind on, makes a budgeted run and an unbudgeted
    one identical by construction — the numbers cannot move, because nothing
    in them depends on what was posted.
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

    result.found, result.missed, result.spurious = _match_defects(case.expected, findings)

    posted_found, _, posted_spurious = _match_defects(case.expected, posted)
    result.posted_found = len(posted_found)
    result.posted_spurious = len(posted_spurious)

    return result
