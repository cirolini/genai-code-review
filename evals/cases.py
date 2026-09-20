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
    suite: str = "small"

    @property
    def is_clean(self) -> bool:
        return not self.expected


def _expected_from(meta) -> tuple:
    return tuple(
        ExpectedDefect(
            file=item["file"],
            line=int(item["line"]),
            categories=tuple(item.get("categories", ())),
            min_severity=item.get("min_severity", "nit"),
        )
        for item in meta.get("expected", [])
    )


def compose(name: str, parts, note: str = "", suite: str = "large") -> Case:
    """
    One large pull request built from several single-defect fixtures.

    The comment budget only does anything on a diff with more findings than it
    will post, and a one-file fixture never produces five. Rather than write a
    forty-file diff by hand and label it again, a large case concatenates
    fixtures that are already written and already labelled: every fixture
    touches a different path, so the result is a valid multi-file diff and the
    seeded defects carry over untouched.

    What this does not give is defect *variety* — the same defects appear here
    as in the small cases. It is built to exercise ranking under volume, not to
    find new failure modes.
    """
    parts = list(parts)
    if not parts:
        raise ValueError(f"composed case {name!r} lists no parts")
    return Case(
        name=name,
        diff="".join(part.diff for part in parts),
        note=note,
        expected=tuple(defect for part in parts for defect in part.expected),
        suite=suite,
    )


def load_cases(directory: Path | None = None, only=None, suite: str | None = "small") -> list[Case]:
    """
    Load fixtures from `directory`.

    A fixture is either a `.diff` plus a `.json` beside it, or a `.json` with a
    `compose` list naming other fixtures to concatenate. Composed cases are
    built after the rest, so they can refer to any fixture in the directory
    regardless of filename order.

    `suite` defaults to `"small"` — the 21 single-file fixtures the published
    results were measured on. The large composed cases re-use those same
    defects, so mixing the two suites would count several defects twice and
    quietly change what precision means. Pass `suite=None` deliberately to get
    both.
    """
    directory = directory or FIXTURES_DIR
    simple, composed_meta = {}, []

    for meta_path in sorted(directory.glob("*.json")):
        meta = json.loads(meta_path.read_text())
        name = meta.get("name", meta_path.stem)

        if meta.get("compose"):
            composed_meta.append((name, meta))
            continue

        diff_path = meta_path.with_suffix(".diff")
        if not diff_path.exists():
            raise FileNotFoundError(f"{meta_path} has no matching .diff")

        simple[name] = Case(
            name=name,
            diff=diff_path.read_text(),
            note=meta.get("note", ""),
            expected=_expected_from(meta),
            suite=meta.get("suite", "small"),
        )

    cases = list(simple.values())

    for name, meta in composed_meta:
        missing = [part for part in meta["compose"] if part not in simple]
        if missing:
            raise KeyError(f"composed case {name!r} refers to unknown fixture(s): {missing}")
        cases.append(
            compose(
                name,
                [simple[part] for part in meta["compose"]],
                note=meta.get("note", ""),
                suite=meta.get("suite", "large"),
            )
        )

    if suite:
        cases = [case for case in cases if case.suite == suite]
    if only:
        cases = [case for case in cases if case.name in only]

    return sorted(cases, key=lambda case: case.name)


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
