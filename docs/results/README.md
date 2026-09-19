# Eval results

**No measured results are committed here yet.** Producing them needs API keys,
and the numbers in this project are meant to be reproducible rather than
asserted — so this directory stays empty until a real run fills it.

## What is measured

21 fixtures in [`evals/fixtures/`](../../evals/fixtures): 15 diffs with a seeded,
labelled defect and 6 clean diffs where the correct answer is silence. All of it
is synthetic code written for this repository.

| Metric | What it means | Why it is here |
|---|---|---|
| Precision | Of the findings reported, how many were real | Wrong comments cost the reviewer more than missing ones |
| Recall | Of the seeded defects, how many were found | The obvious one, and the least interesting |
| Noise rate | Share of clean diffs that drew any comment | **The number this project cares most about.** A bot that comments on a pure rename teaches the reviewer to skim past it |
| Cost per PR | Estimated dollars per reviewed pull request | Whether this is affordable on every push |
| Mean latency | Seconds per review | Whether it blocks the merge |

Recall is measured against everything the model produced; noise is measured
against what survived the comment budget, because that is what reaches a human.

## Reproducing

```bash
make install
export OPENAI_API_KEY=...
make eval PROVIDER=openai
```

Each run sends one request per fixture — 21 requests — and prints the count
before sending anything. `make eval-dry` lists the cases without calling a
provider.

For a second provider:

```bash
export ANTHROPIC_API_KEY=...
make eval PROVIDER=anthropic
```

## The two comparisons the case study needs

**Comment budget on versus off.** Rescored from one set of responses, so it
costs nothing extra:

```bash
make eval-compare PROVIDER=openai
```

**Single model versus panel.** Two providers on every fixture, so roughly
double the cost:

```bash
python -m evals.run --panel openai,anthropic --out docs/results/panel.md
```

## Reading the numbers honestly

Twenty-one fixtures is a small set. It is enough to catch a reviewer that is
badly calibrated — one that says nothing, or one that comments on everything —
and not enough to separate two models that are close. Treat a five-point
difference as noise.

The fixtures are also *seeded*: each defect was deliberately introduced into an
otherwise clean diff, which makes them cleaner than real pull requests, where a
defect is surrounded by unrelated legitimate change. Expect real-world recall to
be lower than anything measured here.

Undefined metrics render as `n/a` rather than `0%`, because reporting 0%
precision on a run that produced no findings would be a false claim rather than
a neutral one.
