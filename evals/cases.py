"""
Loading the eval set.

Each case is a `.diff` and a `.json` beside it listing the defects seeded into
that diff. A case with an empty `expected` list is a clean diff: the correct
behaviour is to say nothing, and anything the reviewer says about it is noise.

All fixtures are synthetic code written for this repository. Nothing here comes
from a private codebase.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# How far a reported line may be from the seeded line and still count as the
# same defect. A reviewer pointing at the call instead of the assignment two
# lines up has still found it.
LINE_TOLERANCE = 4


@dataclass(frozen=True)
class ExpectedDefect:
    file: str
    line: int
    categories: tuple
    min_severity: str = "nit"


@dataclass(frozen=True)
class Case:
    name: str
    diff: str
    note: str
    expected: tuple = field(default_factory=tuple)

    @property
    def is_clean(self) -> bool:
        return not self.expected


def load_cases(directory: Path | None = None, only=None) -> list[Case]:
    """Load every fixture, or only those whose name is in `only`."""
    directory = directory or FIXTURES_DIR
    cases = []

    for meta_path in sorted(directory.glob("*.json")):
        meta = json.loads(meta_path.read_text())
        name = meta.get("name", meta_path.stem)
        if only and name not in only:
            continue

        diff_path = meta_path.with_suffix(".diff")
        if not diff_path.exists():
            raise FileNotFoundError(f"{meta_path} has no matching .diff")

        expected = tuple(
            ExpectedDefect(
                file=item["file"],
                line=int(item["line"]),
                categories=tuple(item.get("categories", ())),
                min_severity=item.get("min_severity", "nit"),
            )
            for item in meta.get("expected", [])
        )
        cases.append(
            Case(
                name=name,
                diff=diff_path.read_text(),
                note=meta.get("note", ""),
                expected=expected,
            )
        )

    return cases


def matches(finding, defect: ExpectedDefect) -> bool:
    """
    Whether a finding has located a seeded defect.

    File must match exactly. The line must be close — a reviewer pointing a
    couple of lines off has still found the problem. Category must be one the
    defect could reasonably be filed under, because "SQL injection" is
    defensible as either `security` or `bug` and penalising that would measure
    taxonomy agreement rather than detection.
    """
    if finding.file != defect.file:
        return False
    if abs(finding.line_start - defect.line) > LINE_TOLERANCE:
        return False
    if defect.categories and finding.category not in defect.categories:
        return False
    return True
