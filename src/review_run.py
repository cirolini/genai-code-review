"""
One complete v3 review.

The order of operations is the argument this project is making, so it is worth
stating plainly:

1. Drop files nobody reviews by hand (lockfiles, generated code, vendored deps).
2. Review only what changed since the last run, not the whole pull request again.
3. Chunk what remains so nothing is silently truncated.
4. Rank findings and post only the best few.
5. Say what was suppressed and what was never looked at.

Every one of those steps removes work from a human's plate without hiding a
real problem — which is the only test that matters here.
"""

import logging
from dataclasses import dataclass, field

import sticky
from budget import BudgetOutcome, apply_budget, fingerprint, risk_map
from chunking import chunk_diff
from diff import parse_diff
from findings import FINDINGS_SCHEMA, SEVERITIES
from panel import merge as merge_panel
from paths import DEFAULT_IGNORE_PATHS, partition
from reviewer import run_review

logger = logging.getLogger(__name__)


@dataclass
class ReviewSettings:
    language: str = "en"
    custom_prompt: str | None = None
    max_comments: int = 5
    min_severity: str = "nit"
    min_confidence: float = 0.0
    # Defaults to skipping lockfiles, generated and vendored code. Constructing
    # ReviewSettings() with no filtering at all would silently contradict what
    # the documented default behaviour is; pass () to turn filtering off.
    ignore_paths: tuple = DEFAULT_IGNORE_PATHS
    incremental: bool = True
    panel: list = field(default_factory=list)


@dataclass
class RunReport:
    """Everything the summary needs to be honest about this run."""

    head_sha: str | None = None
    base_sha: str | None = None
    incremental: bool = False
    reviewed_paths: list = field(default_factory=list)
    ignored_paths: list = field(default_factory=list)
    skipped_paths: list = field(default_factory=list)
    truncated: bool = False
    budget: BudgetOutcome = field(default_factory=BudgetOutcome)
    all_findings: list = field(default_factory=list)
    parse_failed: bool = False
    repaired: bool = False
    panel = None
    results: list = field(default_factory=list)

    @property
    def fully_reviewed(self) -> bool:
        return not (self.skipped_paths or self.truncated or self.parse_failed)


def execute(github_client, build_member, pr_id, settings: ReviewSettings) -> RunReport:
    """
    Run a review and post it.

    `build_member` is a callable taking a provider name (or None for the
    configured default) and returning an LLMProvider, so panel mode can build
    the extra members without this module knowing how providers are made.
    """
    report = RunReport()
    previous = sticky.previous_run(github_client, pr_id)
    report.head_sha = github_client.get_pr_head_sha(pr_id)

    patch, report.base_sha, report.incremental = _select_diff(
        github_client, pr_id, previous, settings, report.head_sha
    )

    parsed = parse_diff(patch)
    reviewable, report.ignored_paths = partition(parsed.paths, settings.ignore_paths)

    if not reviewable:
        _publish(github_client, pr_id, report, parsed, previous, nothing_to_review=True)
        return report

    chunks, report.skipped_paths, report.truncated = chunk_diff(patch, keep_paths=reviewable)
    report.reviewed_paths = [path for chunk in chunks for path in chunk.paths]

    members = settings.panel or [None]
    per_member = []

    for member in members:
        provider = build_member(member)
        member_name = f"{provider.name}/{provider.model}"
        findings = []

        for chunk in chunks:
            outcome = run_review(
                provider,
                chunk.text,
                parsed,
                language=settings.language,
                custom_prompt=settings.custom_prompt,
                schema=FINDINGS_SCHEMA,
            )
            findings.extend(outcome.findings)
            report.repaired = report.repaired or outcome.repaired
            report.parse_failed = report.parse_failed or outcome.parse_failed
            if outcome.result:
                report.results.append(outcome.result)

        per_member.append((member_name, findings))

    if len(per_member) > 1:
        report.panel = merge_panel(per_member)
        report.all_findings = report.panel.findings
    else:
        report.all_findings = per_member[0][1]

    report.budget = apply_budget(
        report.all_findings,
        max_comments=settings.max_comments,
        min_severity=settings.min_severity,
        min_confidence=settings.min_confidence,
        already_posted_keys=set(previous.get("posted", [])),
    )

    _publish(github_client, pr_id, report, parsed, previous)
    return report


def _select_diff(github_client, pr_id, previous, settings, head_sha):
    """
    Decide what to review: everything, or only what is new.

    Falls back to the full diff whenever the incremental path is not clearly
    safe — no previous SHA, the comparison fails, or it comes back empty. A
    review that covers too much is a waste; one that covers too little while
    claiming otherwise is a lie.
    """
    last_sha = previous.get("last_reviewed_sha")

    if not (settings.incremental and last_sha and head_sha and last_sha != head_sha):
        return github_client.get_pr_patch(pr_id), None, False

    try:
        patch = github_client.get_compare_patch(last_sha, head_sha)
    except Exception:
        logger.exception(
            "Could not diff %s..%s; reviewing the whole pull request", last_sha, head_sha
        )
        return github_client.get_pr_patch(pr_id), None, False

    if not patch or not patch.strip():
        logger.info("No changes since %s; reviewing the whole pull request", last_sha)
        return github_client.get_pr_patch(pr_id), None, False

    logger.info("Incremental review of %s..%s", last_sha[:7], head_sha[:7])
    return patch, last_sha, True


def _publish(github_client, pr_id, report, parsed, previous, nothing_to_review=False):
    """Post the inline comments and update the single sticky summary."""
    comments = [_inline_comment(f) for f in report.budget.posted]
    body = build_summary(report, parsed, nothing_to_review=nothing_to_review)

    if comments:
        try:
            github_client.create_review(pr_id, comments, "")
        except Exception:
            logger.exception("Could not post inline comments; the summary will still be posted")

    posted_keys = set(previous.get("posted", []))
    posted_keys.update(fingerprint(f) for f in report.budget.posted)

    sticky.upsert(
        github_client,
        pr_id,
        body,
        sticky.build_state(
            last_reviewed_sha=report.head_sha,
            posted_fingerprints=posted_keys,
            suppressed_count=len(report.budget.suppressed),
        ),
    )


def _inline_comment(finding):
    parts = [
        f"**{finding.severity} · {finding.category}** — {finding.title}",
        "",
        finding.rationale,
    ]
    if finding.suggestion:
        parts += ["", "```suggestion", finding.suggestion.rstrip(), "```"]
    parts += ["", f"<sub>confidence {finding.confidence:.0%}</sub>"]

    comment = {
        "path": finding.file,
        "line": finding.line_end,
        "side": "RIGHT",
        "body": "\n".join(parts),
    }
    if finding.line_end > finding.line_start:
        comment["start_line"] = finding.line_start
        comment["start_side"] = "RIGHT"
    return comment


def build_summary(report, parsed, nothing_to_review=False) -> str:
    """
    The sticky summary.

    Four things, in this order: a verdict, where to look first, what was
    suppressed, and what was not reviewed at all. The last is the one most
    tools leave out, and it is the one that decides whether silence from the
    bot can be trusted.
    """
    lines = ["## Code review"]

    if nothing_to_review:
        lines += ["", "No reviewable files in this change."]
        if report.ignored_paths:
            lines.append(f"{len(report.ignored_paths)} file(s) matched `ignore_paths`.")
        return "\n".join([*lines, "", _footer(report)])

    if report.parse_failed and not report.all_findings:
        lines += [
            "",
            "The model did not return output matching the required schema, even after "
            "a repair attempt. **This diff was not reviewed.**",
        ]
        return "\n".join([*lines, "", _footer(report)])

    lines += ["", _verdict(report)]

    posted = report.budget.posted
    if posted:
        top = risk_map(report.all_findings)
        if top:
            lines += ["", "### Where to look first", ""]
            for path, _score, reason in top:
                lines.append(f"- **`{path}`** — {reason}")

    lines += ["", "### Findings", "", _counts_line(report)]

    suppressed = report.budget.suppressed
    if suppressed:
        lines += [
            "",
            f"<details><summary>{len(suppressed)} finding(s) not posted</summary>",
            "",
            "Held back to keep this review readable, not discarded. Raise "
            "`max_comments`, or lower `min_severity` / `min_confidence`, to see them.",
            "",
        ]
        for finding in sorted(suppressed, key=lambda f: f.rank):
            lines.append(
                f"- `{finding.file}:{finding.line_start}` — **{finding.severity}** "
                f"{finding.title} <sub>({finding.confidence:.0%})</sub>"
            )
        lines += ["", "</details>"]

    coverage = _coverage(report)
    if coverage:
        lines += ["", "### Not reviewed", "", *coverage]

    if report.panel is not None:
        rate = report.panel.agreement_rate
        rate_text = f"{rate:.0%}" if rate is not None else "n/a"
        members = ", ".join(report.panel.members)
        total = report.panel.agreed_count + report.panel.solo_count
        lines += [
            "",
            f"<sub>Panel: {members} · agreement {rate_text} "
            f"({report.panel.agreed_count} of {total} findings reported by "
            "more than one member)</sub>",
        ]

    if report.repaired:
        lines += ["", "<sub>The model's first response was malformed and was repaired.</sub>"]

    return "\n".join([*lines, "", _footer(report)])


def _verdict(report) -> str:
    posted = report.budget.posted
    scope = "the changes since the last review" if report.incremental else "this pull request"

    if not report.all_findings:
        return f"Nothing worth flagging in {scope}."

    worst = min(posted or report.all_findings, key=lambda f: f.rank)
    if worst.severity in ("blocker", "major"):
        return (
            f"{len(report.all_findings)} finding(s) in {scope}; the most serious is a "
            f"**{worst.severity}** in `{worst.file}`. Start there."
        )
    return (
        f"{len(report.all_findings)} finding(s) in {scope}, nothing above "
        f"**{worst.severity}**. Worth a look, not a blocker."
    )


def _counts_line(report) -> str:
    budget = report.budget
    counts = budget.counts_by_severity(report.all_findings)
    by_severity = ", ".join(f"{count} {name}" for name, count in counts.items()) or "none"

    parts = [f"{len(budget.posted)} posted"]
    if budget.over_budget:
        parts.append(f"{len(budget.over_budget)} over budget")
    if budget.below_threshold:
        parts.append(f"{len(budget.below_threshold)} below threshold")
    if budget.already_posted:
        parts.append(f"{len(budget.already_posted)} already raised")

    return f"{', '.join(parts)}. By severity: {by_severity}."


def _coverage(report) -> list[str]:
    """What this run did not look at. Omitted only when there is nothing to say."""
    lines = []
    if report.ignored_paths:
        lines.append(
            f"- {len(report.ignored_paths)} file(s) matched `ignore_paths` "
            "(lockfiles, generated or vendored code, minified assets)."
        )
    if report.skipped_paths:
        listed = ", ".join(f"`{p}`" for p in report.skipped_paths[:5])
        extra = len(report.skipped_paths) - 5
        more = f" and {extra} more" if extra > 0 else ""
        lines.append(f"- Too large for one request, so not reviewed: {listed}{more}.")
    if report.truncated:
        lines.append(
            "- This pull request is large enough that part of it was left out. "
            "**Consider splitting it** — a diff this size is hard for a human to "
            "review properly too."
        )
    if report.incremental:
        lines.append(
            f"- Only changes since `{(report.base_sha or '')[:7]}` were reviewed. "
            "Earlier commits were reviewed in previous runs."
        )
    if report.parse_failed:
        lines.append("- Part of the diff produced unusable model output and was not reviewed.")
    return lines


def _footer(report) -> str:
    if not report.results:
        return ""
    first = report.results[0]
    input_tokens = sum(r.usage.input_tokens or 0 for r in report.results)
    output_tokens = sum(r.usage.output_tokens or 0 for r in report.results)
    latency = sum(r.latency_s for r in report.results)

    footer = f"<sub>{first.provider} · `{first.model}`"
    if input_tokens or output_tokens:
        footer += f" · {input_tokens} in / {output_tokens} out tokens"
    if len(report.results) > 1:
        footer += f" · {len(report.results)} request(s)"
    return footer + f" · {latency:.1f}s</sub>"


__all__ = ["SEVERITIES", "ReviewSettings", "RunReport", "build_summary", "execute"]
