# Eval results

Measured on 2026-09-19 against the 21 fixtures in
[`evals/fixtures/`](../../evals/fixtures): 15 diffs with a seeded, labelled
defect and 6 clean diffs where the correct answer is silence.

| Model | Precision | Recall | Noise rate | Cost / PR | Mean latency |
|---|---|---|---|---|---|
| [`gemini-3.8-flash`](gemini-3.8-flash.md) | 100% | 93% | **0%** | $0.0009 | 5.0s |
| [`gpt-oss-120b`](groq-gpt-oss-120b.md) (via Groq) | 70% | 93% | **83%** | n/a | 1.7s |

No errors in either run; all 21 cases completed for both.

## What these numbers say

**Recall did not separate the two models. Noise did.**

Both found 14 of 15 seeded defects, and both missed the same one
(`missing_test` — neither model flags the absence of a test for newly added
money-handling code). On the metric most review tools report, they are
identical.

On the six clean diffs, `gemini-3.8-flash` said nothing, correctly, six times.
`gpt-oss-120b` commented on five of the six.

This is the whole argument of the project in one table. A reviewer using the
second model would get a comment on nearly every pull request that changed
nothing meaningful — a rename, a docstring, an added test — and would stop
reading the bot within a week. At which point its 93% recall is worth nothing,
because nobody is looking.

## Why the false positives happen

The spurious comments are not random. They are confident claims about code the
model could not see:

- `clean_constant_extract` — "Potential NameError due to undefined
  `DEFAULT_TIMEOUT`". The constant exists; it is just not in the diff.
- `clean_typing` — "Missing import for `Handler` type hint". Same cause.
- `clean_docstring` — "Unexpected indentation causing syntax error", rated
  `blocker`. The surrounding function is not in the diff.

**The reviewer only receives the diff, not the files around it.** That is a
deliberate trade — sending whole files costs far more and is what v2 did badly
— but it produces a specific failure mode: a model asked to review a fragment
will invent problems about the parts it cannot see, and will sound certain
doing it.

A stronger model appears to resist this. A weaker one does not, and no amount
of prompt wording fixed it in these runs.

## What the budget comparison showed: nothing, and why

`--compare-budget` produced identical rows for both models. Two separate
problems were hiding behind that one null result.

**The fixtures were too small.** Neither model ever produced more than five
findings on a single-file diff, so `max_comments: 5` never bound. There is now
a second suite for this — `--suite large` — where each case is a multi-file
pull request composed from the labelled fixtures: `large_mixed_pr` is 15 files
with 10 seeded defects, and `large_clean_pr` is 6 files where the right answer
is still silence. The small suite is unchanged and remains the default, so the
table above stays reproducible.

**The metrics could not have moved anyway.** Precision and recall were
computed over every finding the model produced, and the budget does not change
what the model produces — only what gets posted. So a budgeted run and an
unbudgeted one were identical by construction, on any fixture, of any size.
Scoring now happens twice: once against everything found, and once against
what survived the budget and reached the pull request. The gap between the two
is the budget's entire effect.

Against a stub reviewer that reports all ten seeded defects plus five
confident nits, the two scorings separate exactly as the design predicts:

| | Precision | Recall |
|---|---|---|
| What the model found | 67% | 100% |
| What the reviewer received | 100% | 50% |

That is the trade the budget makes, stated plainly: every comment that arrives
is real, and half the defects never arrive. Whether that is the right trade is
a judgement, not a measurement — but it is now a judgement made against
numbers.

**This has not yet been run against a real model.** The numbers above come
from a stub with scripted output, which proves the harness measures the right
thing and proves nothing about any provider. `make eval-compare` on the large
suite is two requests and needs a key.

## Limits

**21 fixtures is a small set.** It is enough to catch a badly calibrated
reviewer — one that says nothing, or one that comments on everything — and not
enough to separate two models that are close. Treat a five-point difference as
noise. The gap in the table above is 83 points, which is not.

**Seeded defects are easier than real ones.** Each one was deliberately
introduced into an otherwise clean diff. Real pull requests surround a defect
with unrelated legitimate change. Expect real-world recall below 93%.

**One run each.** No repeated sampling, so these are point estimates with
unknown variance.

**Cost for `gpt-oss-120b` is `n/a`** because its pricing is not in the table in
`src/runlog.py`. An unknown model yields no cost rather than a guessed one.

## Reproducing

```bash
make install
export GEMINI_API_KEY=...
make eval PROVIDER=gemini              # the 21 small fixtures, as published
make eval-compare PROVIDER=gemini      # the large suite, with and without the budget
```

Each run sends one request per fixture — 21 requests — and prints the count
before sending anything. `make eval-dry` lists the cases without calling a
provider.

For an OpenAI-compatible endpoint:

```bash
python -m evals.run \
  --provider openai-compatible \
  --base-url https://api.groq.com/openai/v1 \
  --model openai/gpt-oss-120b \
  --api-key "$GROQ_API_KEY" \
  --delay 12 \
  --out docs/results/groq-gpt-oss-120b.md
```

`--delay` paces requests. Without it, a free tier rate-limits partway through
and the cases that fail are not a random sample, which makes the whole run
meaningless. The first attempt at the Groq run lost 10 of 21 cases that way.

## Not yet measured

- **OpenAI's own endpoint.** The adapter is the same class the Groq run
  exercised, so the code path is covered, but `gpt-5.6-luna` itself has never
  been called.
- **Anthropic.** The adapter authenticates and the request reaches Anthropic's
  billing layer, but the account used for testing has no credit, so no response
  has come back.
- **Panel mode.** Needs two working providers in one run.
