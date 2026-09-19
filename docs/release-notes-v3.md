# v3.0.0 release notes

Released 2026-09-19. Published at
https://github.com/cirolini/genai-code-review/releases/tag/v3.0.0

## Decisions taken

- **Version: `v3.0.0`.** The `dlidstrom` fork already publishes `v3.0.x` tags
  from its own repository. Rather than skip a version to avoid the overlap, the
  README and migration guide state the relationship plainly: the two sets of
  tags are independent and not aligned.
- **`mode` defaults to `review`.** A major version is the right moment to make
  v3 do what v3 is for. Workflows that set `mode` explicitly are unaffected;
  `@v2` is untouched and keeps the `files` default.
- **`provider` defaults to `gemini`.** It is the only configuration with
  measured numbers behind it — 100% precision, 93% recall, 0% noise, $0.0009
  per pull request. A workflow passing the deprecated `openai_api_key` without
  a `provider` stays on OpenAI.

## Still open

### Marketplace

The existing listing is named "ChatGPT GitHub Actions", which no longer
describes the action. Updating it is a separate, explicit step and has not been
done.

### Two adapters remain unverified against a live API

`openai` shares its class with `openai-compatible`, which is verified against
Groq, so the code path is exercised — but `gpt-5.6-luna` itself has never been
called. `anthropic` authenticates and reaches Anthropic's billing layer, but
the account used for testing has no credit.

Neither is the default any more, which is why this no longer blocks the
release.

---

## Notes as published

### v3.0.0

v3 rebuilds this action around a single idea: the scarce resource in code review
is the reviewer's attention, and a bot that posts forty comments spends more of
it than it returns.

**Two changed defaults.** `mode` now defaults to `review`, so a workflow that
never set `mode` gets inline comments instead of one summary comment — pin
`mode: files` to keep the old output. And `provider` now defaults to `gemini`,
though a workflow passing the deprecated `openai_api_key` without a `provider`
stays on OpenAI.

Every v2 input still works, and `@v2` itself is untouched. See
[the migration guide](migrating-v2-to-v3.md).

#### Multiple providers

`provider` selects Google Gemini (the default), OpenAI, Anthropic, or any
OpenAI-compatible server — Ollama, vLLM, Azure OpenAI, OpenRouter — via `base_url`. New inputs:
`provider`, `model`, `api_key`, `base_url`, `temperature`, `max_tokens`. The
`openai_*` inputs remain as aliases.

Transient failures are retried with backoff; permanent ones are not, because
retrying a rejected key only delays the message you need. A provider failure is
now reported in the pull request and fails the check, rather than surfacing only
in a log — a review that silently did not happen looks exactly like a review
that found nothing.

#### Inline comments on the right lines

With `mode: review`, the model returns findings matching a JSON schema — file,
line range, severity, category, confidence, title, rationale, optional
suggestion — validated in code, with one repair attempt when it does not match.
Findings are posted as inline comments grouped into a single review.

#### Review pressure controls

- `max_comments` (default 5), ranked by severity then confidence. Suppressed
  findings are counted and listed, never dropped.
- `min_severity` and `min_confidence`.
- One sticky summary comment, edited in place instead of a new one per push.
- Incremental review: on a push, only the new commits are reviewed, and findings
  already raised are not repeated.
- `ignore_paths`, defaulting to lockfiles, generated and vendored code,
  snapshots and minified assets.
- Large diffs are chunked, and anything that did not fit is reported rather than
  silently truncated.
- `panel` (experimental): two providers merged, with agreement as a confidence
  signal. Roughly double the cost.

#### Measured

| Model | Precision | Recall | Noise rate | Cost / PR |
|---|---|---|---|---|
| `gemini-3.8-flash` | 100% | 93% | 0% | $0.0009 |
| `gpt-oss-120b` | 70% | 93% | 83% | n/a |

21 fixtures, 15 with a seeded defect and 6 clean. Recall did not separate the
two models; noise did. Full numbers and limits in [`docs/results/`](results/).

#### Measurement

Every run writes a JSON log — provider, model, tokens, estimated cost, latency,
findings by severity, posted versus suppressed, coverage — containing no
credentials, no diff and no source code.

`evals/` holds 21 fixtures with seeded, labelled defects plus clean diffs, and
`make eval` scores precision, recall, noise rate, cost per pull request and
latency.

#### Fixed

Everything in v2.1: the container entrypoint path (#47), the unpinned `httpx`
that broke client construction, and the deprecated default model. Also the patch
parser, which split on the bare substring `diff` and broke on any diff that
mentioned the word (#28).

#### Security

The diff is treated as untrusted input: fenced with a per-request random
sentinel, with instructions placed after the data, and the model told that
injection attempts are themselves reportable. Use `pull_request`, not
`pull_request_target`, for pull requests from forks.
