# v3 release notes (draft — not tagged)

This file is prepared, not published. Tagging a release, moving a tag and
publishing to the Marketplace are all decisions for the maintainer.

## Open decisions

These need answering before anything is tagged.

### 1. Version number

`dlidstrom/genai-code-review`, a fork of this repository, already publishes tags
`v3.0.0` through `v3.0.8`. Someone searching for "genai-code-review v3" will
find both.

- **`v3.0.0`** — the natural number for this work. The README and migration
  guide now state the fork relationship plainly, so the ambiguity is documented
  rather than hidden.
- **`v3.1.0`** — sidesteps the overlap entirely at the cost of a version number
  that looks like it skipped a release.

### 2. Should `mode` default to `review`?

It currently defaults to `files`, the v2 behaviour, so that no existing workflow
changes underneath its owner. A major version is the conventional moment to
change a default like this.

- **Keep `files`** — nothing surprises anyone; v3's main feature stays opt-in
  and most users never see it.
- **Default to `review`** — v3 does what v3 is for. Existing workflows that
  pinned `mode` explicitly are unaffected; those that did not get inline
  comments instead of one summary comment, on a major version bump.

### 3. Marketplace

The existing listing is "ChatGPT GitHub Actions", which no longer describes the
action — it supports four providers. Updating the listing is a separate,
explicit step from tagging.

### 4. Not verified against a live API

No part of v3 has run against a real provider. The repository's
`OPENAI_API_KEY` secret is expired, so every review the CI attempted failed with
a 401 before reaching the model.

What that means concretely: the four provider adapters, the structured-output
parameters, and the model IDs are all checked against the providers' own
documentation and against the installed SDKs, but no response has ever come
back. `docs/results/` is empty for the same reason.

**A release should not go out before at least one end-to-end run succeeds.**

---

## Draft notes

### v3.0.0

v3 rebuilds this action around a single idea: the scarce resource in code review
is the reviewer's attention, and a bot that posts forty comments spends more of
it than it returns.

**Nothing in this release is required of you.** Every v2 input still works, and
`mode` still defaults to the v2 behaviour. See
[the migration guide](migrating-v2-to-v3.md).

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
