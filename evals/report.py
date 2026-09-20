"""Rendering eval results as Markdown."""


def _pct(value):
    return f"{value:.0%}" if value is not None else "n/a"


def _num(value, fmt="{:.2f}"):
    return fmt.format(value) if value is not None else "n/a"


def _money(value):
    return f"${value:.4f}" if value is not None else "n/a"


def summary_table(rows) -> str:
    """
    One row per configuration.

    `rows` is a list of (label, Scores).
    """
    header = (
        "| Configuration | Precision | Recall | F1 | Noise rate | "
        "Cost / PR | Mean latency |\n"
        "|---|---|---|---|---|---|---|"
    )
    lines = [header]
    for label, scores in rows:
        lines.append(
            f"| {label} | {_pct(scores.precision)} | {_pct(scores.recall)} | "
            f"{_num(scores.f1)} | {_pct(scores.noise_rate)} | "
            f"{_money(scores.cost_per_pr)} | {_num(scores.mean_latency)}s |"
        )
    return "\n".join(lines)


def per_case_table(scores) -> str:
    header = (
        "| Case | Seeded | Found | Missed | Spurious | Posted |\n"
        "|---|---|---|---|---|---|"
    )
    lines = [header]
    for case in scores.cases:
        seeded = len(case.found) + len(case.missed)
        mark = "clean" if case.is_clean else str(seeded)
        lines.append(
            f"| `{case.name}` | {mark} | {len(case.found)} | {len(case.missed)} | "
            f"{len(case.spurious)} | {case.posted_count} |"
        )
    return "\n".join(lines)


def detail(scores) -> str:
    """What was missed and what was invented, by name — the useful part."""
    lines = []
    missed = [(c.name, d) for c in scores.cases for d in c.missed]
    if missed:
        lines += ["", "**Missed defects**", ""]
        for name, d in missed:
            categories = "/".join(d.categories)
            lines.append(f"- `{name}` — {d.file}:{d.line} ({categories})")

    noisy = [(c.name, f) for c in scores.cases if c.is_clean for f in c.spurious]
    if noisy:
        lines += ["", "**Comments on clean diffs**", ""]
        lines += [f"- `{name}` — {f.severity}: {f.title}" for name, f in noisy]

    errors = [c for c in scores.cases if c.error]
    if errors:
        lines += ["", "**Errors**", ""]
        lines += [f"- `{c.name}` — {c.error}" for c in errors]

    return "\n".join(lines)


def budget_table(rows) -> str:
    """
    What the reviewer actually received, as opposed to what the model produced.

    Separate from `summary_table` because it answers a different question.
    Precision there is a property of the model; precision here is a property of
    the review, and the comment budget only moves the second one.
    """
    header = (
        "| Configuration | Findings | Posted | Suppressed | "
        "Posted precision | Posted recall |\n"
        "|---|---|---|---|---|---|"
    )
    lines = [header]
    for label, scores in rows:
        findings = scores.true_positives + scores.false_positives
        posted = sum(case.posted_count for case in scores.cases)
        lines.append(
            f"| {label} | {findings} | {posted} | {max(findings - posted, 0)} | "
            f"{_pct(scores.posted_precision)} | {_pct(scores.posted_recall)} |"
        )
    return "\n".join(lines)


def _budget_bound(rows) -> bool:
    """True when at least one configuration held something back."""
    return any(
        (scores.true_positives + scores.false_positives)
        > sum(case.posted_count for case in scores.cases)
        for _, scores in rows
    )


def full_report(title, rows, primary=None) -> str:
    parts = [f"# {title}", "", summary_table(rows)]

    if _budget_bound(rows):
        parts += ["", "## What reached the reviewer", "", budget_table(rows)]
    else:
        parts += [
            "",
            "The comment budget never bound: every finding fit inside "
            "`max_comments`, so what the reviewer received is what the model "
            "produced and the table above describes both. Run `--suite large` "
            "for cases with more findings than the budget will post.",
        ]

    if primary is not None:
        label, scores = primary
        parts += ["", f"## Per case — {label}", "", per_case_table(scores), detail(scores)]
    return "\n".join(parts) + "\n"
