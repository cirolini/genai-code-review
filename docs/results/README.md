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

## The budget, measured — and it did not do what I expected

Measured on 2026-09-20, `gpt-oss-120b` via Groq, `--suite large`, two cases.
Full output in [`groq-gpt-oss-120b-large.md`](groq-gpt-oss-120b-large.md).

| | Precision | Recall |
|---|---|---|
| What the model found | 83% | 100% |
| What the reviewer received (budget 5) | **71%** | 50% |
| What the reviewer received (no budget) | 83% | 100% |

**The budget made the aggregate precision worse.** That is the opposite of the
result the design predicts, and the reason is worth more than the number.

Per case:

| Case | Findings | Real | Spurious | Posted |
|---|---|---|---|---|
| `large_mixed_pr` (10 seeded) | 10 | 10 | 0 | 5 |
| `large_clean_pr` (clean) | 2 | 0 | 2 | 2 |

On the 15-file pull request the model found **all ten** seeded defects and
invented nothing. The budget then cut five of them. On the clean pull request
it invented two problems, and the budget cut neither — with only two findings,
the cap never came near binding.

So on this run the budget removed exclusively true positives and left every
false positive in place. **A cap on volume does nothing about a review that is
entirely noise**, because noise on a quiet diff is not competing with anything
for the slots.

This does not make the budget worthless: five comments instead of ten on a
large pull request is genuinely less attention spent, which is the thing it
was built to manage. But the claim it was *also* raising the quality of what
gets through does not survive contact with this eval. Precision at the
reviewer is governed by `min_confidence` and `min_severity` — the filters that
act on a finding's own merits — not by a cap that only engages when findings
are plentiful.

Two caveats before anyone leans on this. It is one run of two cases, which is
not a basis for a strong claim in either direction. And `gpt-oss-120b` is the
noisy model of the two measured here — the same context-blindness as on the
small suite, both spurious comments being confident claims about symbols
defined outside the diff. A model with `gemini-3.8-flash`'s 0% noise rate
would have nothing for the budget to fail to remove.

## The default response cap loses large reviews entirely

The first attempt at the run above produced no review at all for
`large_mixed_pr`:

```
BadRequestError: 400 - Failed to validate JSON. Please adjust your prompt.
  'failed_generation': ''
```

The action's default `max_tokens` is 2048. Ten findings with rationales do not
fit in 2048 tokens, the response is truncated mid-JSON, and structured output
then fails validation at the provider. Confirmed directly:

| `max_tokens` | Result |
|---|---|
| 2048 (the default) | 400, no review |
| 8192 | 11 findings, 3426 output tokens |

The pull requests where a review matters most are exactly the ones this
breaks on, and the error a user sees — "Please adjust your prompt" — points
nowhere near the cause. The measurement above therefore used
`--max-tokens 8192`.

Raising the default is a behaviour change on every existing workflow's bill,
so it is not made here.

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

The large suite needs a bigger response cap than the action's default, or the
review is lost to truncation — see above:

```bash
python -m evals.run --suite large --compare-budget --max-tokens 8192 \
  --provider gemini --delay 75
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
- **Panel mode.** Needs two working providers in one run. Only one usable key
  exists at the moment, so this stays untested.
