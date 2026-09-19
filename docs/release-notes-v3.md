# v3 release notes (draft — not tagged)

This file is prepared, not published. Tagging a release, moving a tag and
publishing to the Marketplace are all decisions for the maintainer.

## Decisions taken

- **Version: `v3.0.0`.** The `dlidstrom` fork already publishes `v3.0.x` tags
  from its own repository. Rather than skip a version to avoid the overlap, the
  README and migration guide state the relationship plainly: the two sets of
  tags are independent and not aligned.
- **`mode` defaults to `review`.** A major version is the right moment to make
  v3 do what v3 is for. Workflows that set `mode` explicitly are unaffected;
  `@v2` is untouched and keeps the `files` default.

## Still open

### Marketplace

The existing listing is named "ChatGPT GitHub Actions", which no longer
describes the action — it supports four providers. Updating the listing is a
separate, explicit step from tagging and has not been done.

### Live verification: two of four providers

The pipeline has now run end to end against real models, and
[`docs/results/`](results/) has measured numbers.

| Provider | Status |
|---|---|
| `gemini` | **Verified.** 21/21 eval cases, 100% precision, 93% recall, 0% noise |
| `openai-compatible` | **Verified** against Groq, 21/21 cases |
| `openai` | **Not verified.** Same adapter class as `openai-compatible`, so the code path is covered, but `gpt-5.6-luna` itself has never been called |
| `anthropic` | **Not verified.** The adapter authenticates and reaches Anthropic's billing layer, but the test account has no credit, so no response has come back |

Running it caught three real bugs that 213 passing tests had not: the Gemini
client being garbage collected mid-call, Gemini rejecting the
`additionalProperties` that OpenAI strict mode requires, and strict mode
forbidding the optional `suggestion` property. All three are fixed, with tests.

**Remaining risk before tagging:** `gpt-5.6-luna` is the default model and has
never been called. The adapter around it is exercised, and the model ID is from
OpenAI's own documentation, but a working `OPENAI_API_KEY` and one green run
would close the last gap.

---

## Draft notes

### v3.0.0

v3 rebuilds this action around a single idea: the scarce resource in code review
is the reviewer's attention, and a bot that posts forty comments spends more of
it than it returns.

**One breaking change:** `mode` now defaults to `review`, so a workflow that
never set `mode` gets inline comments instead of a single summary comment. Pin
`mode: files` to keep the old output. Every v2 input still works, and `@v2`
itself is untouched. See [the migration guide](migrating-v2-to-v3.md).

#### Multiple providers

`provider` selects OpenAI, Anthropic, Google Gemini, or any OpenAI-compatible
server — Ollama, vLLM, Azure OpenAI, OpenRouter — via `base_url`. New inputs:
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
