"""
Eval runner.

    python -m evals.run --provider openai --model gpt-5.6-luna
    python -m evals.run --provider openai --compare-budget
    python -m evals.run --panel openai,anthropic

Runs every fixture through the real review path — the same prompt, schema,
parsing and budget the action uses — and scores the result. Running it costs
real money, so the number of requests is printed before anything is sent.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from budget import apply_budget
from diff import parse_diff
from evals.cases import load_cases
from evals.metrics import Scores, score_case
from evals.report import full_report
from findings import FINDINGS_SCHEMA
from panel import merge as merge_panel
from providers import ProviderError, build_provider
from reviewer import run_review
from runlog import estimate_cost


def review_case(case, providers, max_comments, min_severity, min_confidence):
    """Run one fixture through the review path and score it."""
    parsed = parse_diff(case.diff)
    per_member, usage_in, usage_out, latency, cost = [], 0, 0, 0.0, 0.0
    cost_known = False

    for provider in providers:
        outcome = run_review(provider, case.diff, parsed, schema=FINDINGS_SCHEMA)
        per_member.append((f"{provider.name}/{provider.model}", outcome.findings))

        if outcome.result:
            tokens_in = outcome.result.usage.input_tokens or 0
            tokens_out = outcome.result.usage.output_tokens or 0
            usage_in += tokens_in
            usage_out += tokens_out
            latency += outcome.result.latency_s
            estimated = estimate_cost(outcome.result.model, tokens_in, tokens_out)
            if estimated is not None:
                cost += estimated
                cost_known = True

    if len(per_member) > 1:
        findings = merge_panel(per_member).findings
    else:
        findings = per_member[0][1]

    budget = apply_budget(
        findings,
        max_comments=max_comments,
        min_severity=min_severity,
        min_confidence=min_confidence,
    )

    return score_case(
        case,
        findings,
        budget.posted,
        usage_in=usage_in,
        usage_out=usage_out,
        latency=latency,
        cost=round(cost, 6) if cost_known else None,
    )


def run(cases, providers, *, max_comments, min_severity, min_confidence, label) -> Scores:
    scores = Scores()
    for index, case in enumerate(cases, start=1):
        print(f"  [{index}/{len(cases)}] {case.name} ... ", end="", flush=True)
        started = time.monotonic()
        try:
            result = review_case(case, providers, max_comments, min_severity, min_confidence)
            print(
                f"{len(result.found)} found, {len(result.missed)} missed, "
                f"{len(result.spurious)} spurious ({time.monotonic() - started:.1f}s)"
            )
        except ProviderError as exc:
            # One failing case must not lose the results of the other twenty.
            result = score_case(case, [], [])
            result.error = str(exc)
            print(f"ERROR: {exc}")
        scores.cases.append(result)
    print(f"  {label}: precision {scores.precision}, recall {scores.recall}")
    return scores


def main(argv=None):
    parser = argparse.ArgumentParser(prog="evals.run")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--panel", default=None, help="Comma-separated providers to run as a panel")
    parser.add_argument("--max-comments", type=int, default=5)
    parser.add_argument("--min-severity", default="nit")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--only", default=None, help="Comma-separated case names")
    parser.add_argument(
        "--compare-budget",
        action="store_true",
        help="Also score the same run with the comment budget removed",
    )
    parser.add_argument("--out", default=None, help="Write the Markdown report here")
    parser.add_argument("--json-out", default=None, help="Write raw scores here")
    parser.add_argument("--dry-run", action="store_true", help="List what would run, send nothing")
    args = parser.parse_args(argv)

    only = set(args.only.split(",")) if args.only else None
    cases = load_cases(only=only)
    if not cases:
        print("No cases matched.", file=sys.stderr)
        return 1

    member_names = [n.strip() for n in args.panel.split(",")] if args.panel else [args.provider]
    requests = len(cases) * len(member_names)

    print(f"{len(cases)} case(s) x {len(member_names)} provider(s) = {requests} request(s)")
    if args.dry_run:
        for case in cases:
            kind = "clean" if case.is_clean else f"{len(case.expected)} seeded"
            print(f"  {case.name:26} {kind}")
        return 0

    providers = []
    for name in member_names:
        providers.append(
            build_provider(
                name,
                model=args.model if len(member_names) == 1 else None,
                api_key=args.api_key,
                base_url=args.base_url,
            )
        )

    label = " + ".join(f"{p.name}/{p.model}" for p in providers)
    print(f"Running: {label}")

    scores = run(
        cases,
        providers,
        max_comments=args.max_comments,
        min_severity=args.min_severity,
        min_confidence=args.min_confidence,
        label=label,
    )

    rows = [(f"{label} (budget {args.max_comments})", scores)]

    if args.compare_budget:
        # Rescore the findings already obtained, without spending again.
        unbudgeted = Scores()
        for case_result in scores.cases:
            copy = type(case_result)(**vars(case_result))
            copy.posted_count = len(case_result.found) + len(case_result.spurious)
            unbudgeted.cases.append(copy)
        rows.append((f"{label} (no budget)", unbudgeted))

    report = full_report(
        f"Eval results — {label}", rows, primary=(label, scores)
    )
    print()
    print(report)

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        Path(args.out).write_text(report)
        print(f"Wrote {args.out}")

    if args.json_out:
        payload = {
            "label": label,
            "precision": scores.precision,
            "recall": scores.recall,
            "f1": scores.f1,
            "noise_rate": scores.noise_rate,
            "cost_per_pr": scores.cost_per_pr,
            "mean_latency": scores.mean_latency,
            "errors": scores.errors,
            "cases": [
                {
                    "name": c.name,
                    "clean": c.is_clean,
                    "found": len(c.found),
                    "missed": len(c.missed),
                    "spurious": len(c.spurious),
                    "posted": c.posted_count,
                    "error": c.error,
                }
                for c in scores.cases
            ],
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=2))
        print(f"Wrote {args.json_out}")

    return 1 if scores.errors == len(scores.cases) else 0


if __name__ == "__main__":
    raise SystemExit(main())
