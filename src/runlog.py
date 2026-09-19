"""
The per-run JSON artifact.

Every run writes what it did and what it cost, so that claims about the tool
can be checked rather than asserted. This is what makes the case study
measurable instead of anecdotal.

What is deliberately *not* in here: the API key, the diff, the code under
review, and the findings' rationale text. A run log is uploaded as a build
artifact and is readable by anyone who can see the repository's Actions tab.
Finding titles are included because they are the tool's own output and are
already visible in the pull request; source code is not, because it might not
be.
"""

import json
import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Cost per million tokens, (input, output), checked against each provider's
# pricing page on 2026-09-19. Used only to estimate; a missing entry yields a
# null cost rather than a wrong one.
PRICING = {
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-sol": (4.00, 20.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # Promotional rate through 2026-12-31; rises to (1.50, 7.50) after.
    "gemini-3.8-flash": (0.75, 3.75),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated dollar cost, or None when the model's pricing is unknown."""
    rates = PRICING.get(model)
    if not rates:
        return None
    return round(input_tokens / 1e6 * rates[0] + output_tokens / 1e6 * rates[1], 6)


def build(report, *, repository=None, pr_id=None, run_id=None) -> dict:
    """Turn a RunReport into the artifact payload."""
    input_tokens = sum((r.usage.input_tokens or 0) for r in report.results)
    output_tokens = sum((r.usage.output_tokens or 0) for r in report.results)
    first = report.results[0] if report.results else None

    findings_by_severity: dict[str, int] = {}
    for finding in report.all_findings:
        findings_by_severity[finding.severity] = findings_by_severity.get(finding.severity, 0) + 1

    payload = {
        "schema_version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "repository": repository or os.getenv("GITHUB_REPOSITORY"),
        "pull_request": pr_id,
        "run_id": run_id or os.getenv("GITHUB_RUN_ID"),
        "provider": first.provider if first else None,
        "model": first.model if first else None,
        "requests": len(report.results),
        "tokens": {"input": input_tokens, "output": output_tokens},
        "estimated_cost_usd": estimate_cost(first.model, input_tokens, output_tokens)
        if first
        else None,
        "latency_seconds": round(sum(r.latency_s for r in report.results), 3),
        "incremental": report.incremental,
        "findings": {
            "total": len(report.all_findings),
            "by_severity": findings_by_severity,
            "posted": len(report.budget.posted),
            "suppressed_over_budget": len(report.budget.over_budget),
            "suppressed_below_threshold": len(report.budget.below_threshold),
            "already_posted": len(report.budget.already_posted),
        },
        "coverage": {
            "files_reviewed": len(report.reviewed_paths),
            "files_ignored": len(report.ignored_paths),
            "files_skipped": len(report.skipped_paths),
            "truncated": report.truncated,
            "parse_failed": report.parse_failed,
            "repaired": report.repaired,
            "fully_reviewed": report.fully_reviewed,
        },
        # Titles only. Never the rationale, the suggestion, or any source line.
        "posted_titles": [f.title for f in report.budget.posted],
    }

    if report.panel is not None:
        payload["panel"] = {
            "members": report.panel.members,
            "agreed": report.panel.agreed_count,
            "solo": report.panel.solo_count,
            "agreement_rate": report.panel.agreement_rate,
        }

    return payload


def write(report, path: str, **kwargs) -> str | None:
    """
    Write the run log, returning the path.

    A failure here must never fail the review: the log is evidence about the
    run, not part of it.
    """
    try:
        payload = build(report, **kwargs)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        logger.info("Wrote run log to %s", path)
        return path
    except Exception:
        logger.exception("Could not write the run log; the review itself is unaffected")
        return None
