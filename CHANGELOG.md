# Changelog

## v3.0.1 — 2026-09-21

### Added

- **A large eval suite.** `--suite large` runs multi-file pull requests
  composed from the labelled fixtures: `large_mixed_pr` (15 files, 10 seeded
  defects) and `large_clean_pr` (6 files, nothing wrong). The comment budget
  cannot bind on a single-file fixture, so until now it was never exercised.
  `--suite small`, the 21 published fixtures, stays the default.
- **Acceptance signal.** `python -m evals.feedback --repo owner/name` (also
  `make feedback`) reads a repository the action has run on and reports what
  reviewers did with its comments: 👍/👎 reactions, replies, thread resolution,
  and the share nobody engaged with. Read-only, no model call. The signals are
  reported separately rather than averaged — a resolved thread means the
  conversation ended, not that the finding was right.

### Security

- **`.genai-review.yml` is now read from the pull request's base branch.** It
  was read from the working directory, which meant two things. With an
  `actions/checkout` step, the file came from the pull request itself, so
  whoever opened it could set `ignore_paths: ["**"]` or `max_comments: 0` and
  review their own change out of existence, or point `base_url` at their own
  server and receive the API key. Without a checkout — which is what the README
  recommends — the file was silently never read at all. It is now fetched over
  the API from the base commit, so it works without a checkout and a pull
  request cannot configure its own review.
- **`base_url` can no longer be set in `.genai-review.yml`.** It decides which
  server receives the API key, so it is an action input only.

### Fixed

- **Files that were not reviewed dropped out of the summary on the next push.**
  The last reviewed SHA advanced even when a run skipped files as too large,
  truncated the diff, or got unusable output from the model. The next push
  diffed from there, so those files were neither reviewed nor listed under
  "Not reviewed" — the one promise the summary exists to keep. The SHA now
  advances only when a run covered everything, and the summary says the next
  push will review the earlier range again.
- **Findings counted as posted when the review failed to post.** If GitHub
  rejected the review, its findings were still recorded as posted and never
  tried again. They are now listed in the summary instead and retried on the
  next push.
- **Incremental review broke after merging the base branch or rebasing.** The
  comparison with the last reviewed commit then contains changes that are not
  part of the pull request, and GitHub rejects the whole review with a 422 over
  a single comment on one of them. The comparison is now checked first: a
  rewritten history or a merge commit in the range falls back to reviewing the
  whole pull request, and the summary says why. Findings are also placed
  against the pull request's own diff, so a file outside it is never reviewed
  or commented on.
- **One-click suggestions could land on the wrong lines.** A finding up to
  three lines off the diff is moved to the nearest line, or its range is
  shortened to fit a hunk, but its `suggestion` was still offered as a one-click
  change — so "Commit suggestion" replaced code the suggestion was not written
  for. A moved finding now shows its suggestion as a plain code block.
- **The action was listed as "ChatGPT GitHub Actions".** `action.yml` now names
  it GenAI Code Review and describes what v3 does.
- **The migration guide said `@v2` was untouched.** It was moved once, to the
  fix-only v2.1; the guide and the v3 release notes now say so.

- **The comment budget was unmeasurable.** Precision and recall were computed
  over every finding the model produced, and the budget changes only what is
  posted — so a budgeted and an unbudgeted run were identical by construction,
  on any fixture of any size. Scoring now runs twice, once against everything
  found and once against what reached the pull request, and the report carries
  a "What reached the reviewer" table with the second pair. The published
  small-suite numbers are unaffected.

### Changed

- **The default `max_tokens` is now 8192** (was 2048). Ten findings with
  rationales do not fit in 2048: the response truncates mid-JSON, structured
  output then fails validation at the provider, and the pull request gets no
  review at all — with a 400 saying "Please adjust your prompt", which points
  nowhere near the cause. Measured on a 15-file pull request: 2048 returned
  nothing, 8192 returned 11 findings in 3426 output tokens. The pull requests
  the comment budget exists for were exactly the ones this broke on.

  This does not raise the cost of a review that was already working. A cap is
  not a purchase — a review producing four findings bills four findings at
  either setting. Pass `max_tokens` to set it back.

## v3.0.0 — 2026-09-19

### Fixed

- **Gemini requests failed entirely.** The client was garbage collected as soon
  as `.models` was resolved, closing the transport before the request went out.
- **Structured output was rejected by both OpenAI and Gemini.** Gemini returns
  400 on the `additionalProperties` that OpenAI's strict mode requires, and
  strict mode forbids optional properties — `required` must name every key.
  The canonical schema is now provider-neutral and each adapter transforms it.

### Changed (breaking)

- **The default provider is now `gemini`**, the configuration with measured
  results behind it. A workflow that passes the deprecated `openai_api_key` and
  does not set `provider` stays on OpenAI, so an existing key is never sent to
  a different vendor by a moving default.

- **`mode` now defaults to `review`** instead of `files`. A workflow that never
  set `mode` gets inline comments on the diff instead of one long summary
  comment. Workflows that set `mode` explicitly are unaffected, and the `v2`
  tag keeps the `files` default — this applies only when the pin moves to `v3`. Pin
  `mode: files` to keep the previous output.

### Added

- **Repository configuration.** Settings can live in `.genai-review.yml` at the
  repository root instead of the workflow file. Action inputs take precedence.
  There is deliberately no `api_key` key: credentials belong in a secret.
- Documentation: a rewritten README, `docs/case-study.md`,
  `docs/migrating-v2-to-v3.md`, `docs/results/`, and a commented
  `.genai-review.yml.example`.

- **Run log.** Every review writes a JSON artifact with provider, model, tokens,
  estimated cost, latency, findings by severity, posted versus suppressed, and
  what was not reviewed. Never contains the API key, the diff, the code under
  review, or the findings' rationale text.
- **Eval set and runner.** 21 fixtures — 15 diffs with a seeded labelled defect,
  6 clean diffs where the right answer is silence — and `python -m evals.run`,
  which scores precision, recall, noise rate, cost per pull request and latency,
  and prints a Markdown table. `make eval` wraps it.

- **`mode: review`** — structured findings posted as inline comments on the
  right diff lines, grouped into a single review. `files` and `patch` keep
  doing exactly what they did in v2, so no existing workflow changes behaviour.
- **Schema-validated model output.** Findings carry file, line range, severity
  (`blocker`/`major`/`minor`/`nit`), category, confidence, title, rationale and
  an optional suggestion. Providers that support structured output natively are
  asked to use it; otherwise output is validated and the model gets exactly one
  repair attempt with a specific list of what was wrong.
- **A real diff parser.** v2 split the patch on the bare substring `diff`,
  which also split on the word wherever it appeared in the code under review —
  the cause of issue #28.
- **Prompt-injection defences.** The diff is delimited by a per-call random
  sentinel it cannot forge, the instructions come after the data, and the model
  is told the diff is untrusted and that injection attempts are themselves
  reportable.

- **Multi-provider support.** `provider` selects OpenAI, Anthropic, Google
  Gemini, or any OpenAI-compatible server (Ollama, vLLM, Azure OpenAI,
  OpenRouter) via `base_url`. New inputs: `provider`, `model`, `api_key`,
  `base_url`, `temperature`, `max_tokens`.
- **Retries with backoff** on transient provider failures (429, 5xx, timeouts),
  and no retries on permanent ones — retrying a rejected key only delays the
  message the user needs.
- **Failures are reported in the pull request** rather than only in the run log,
  and the check fails. A review that silently did not happen is indistinguishable
  from a review that found nothing, which is the worse outcome for a review bot.
- Review comments now carry a footer naming the provider, model, token counts
  and latency.

### Changed

- Model IDs and defaults live in `src/config.py` rather than being spread across
  adapters. Per-provider defaults are cost-conscious, not each vendor's
  strongest model.
- The comment header no longer says "ChatGPT's code review", which was wrong as
  soon as the reviewer was Claude or Gemini.

### Deprecated

- `openai_api_key`, `openai_model`, `openai_temperature` and `openai_max_tokens`
  are aliases for the new inputs. They still work; a v2 workflow runs on v3
  unchanged.

### Removed

- `src/clients/openai_client.py`, superseded by `src/providers/`.

## v2.1 — 2026-09-19

A maintenance release. No new features and no input changes: `v2.1` exists
because `v2` had stopped working, in two independent ways.

### Fixed

- **The action could not start on any repository but this one** (#47). GitHub
  runs container actions with `--workdir /github/workspace`, which overrides the
  image's `WORKDIR`, so the relative `CMD ["python", "src/main.py"]` resolved
  against the caller's checked-out repository and failed with
  `can't open file '/github/workspace/src/main.py'`. The entrypoint is now
  absolute. Reported by @Asthethi; fix from @arjunsuresh in #50.

  This repository's own workflow checked the repository out before running the
  action, which put a `src/main.py` on the container's working directory and
  made the action appear to work here while it failed everywhere else. That
  checkout has been removed, and CI now builds the image and runs it the way
  GitHub does.

- **The OpenAI client could not be constructed.** `openai` was pinned to
  `1.30.1` but `httpx` was not pinned at all. `httpx` 0.28 removed the `proxies`
  argument that `openai` 1.30 passes, so a fresh build failed with
  `Client.__init__() got an unexpected keyword argument 'proxies'`. All
  dependencies, including transitive ones that affect startup, are now pinned,
  and the Python base image is pinned to a patch version.

### Changed

- **Default model is now `gpt-5.6-luna`** (was `gpt-3.5-turbo`, which is
  deprecated and loses API access on 2026-10-23). `gpt-5.6-luna` is cheaper than
  `gpt-3.5-turbo` on both input and output tokens, so this does not raise the
  cost of an existing workflow. Pass `openai_model` to choose a different one.

- Dependencies: `openai` 1.30.1 → 1.109.1, `PyGithub` 2.3.0 → 2.10.0,
  `requests` 2.31.0 → 2.34.2, `httpx` pinned at 0.28.1.

### Documentation

- The workflow example now includes the required `permissions` block. Missing
  `pull-requests: write` was a recurring cause of "it runs but posts nothing".
- The configuration reference documented an `openai_engine` input that the
  action never read. The correct name is `openai_model`.
- Removed `actions/checkout` from the example. This action reads the pull
  request over the API and does not need the repository on disk.

### Upgrading

None required. `v2` now points at this release, and every existing input keeps
its previous meaning. If you pinned `openai_model: "gpt-3.5-turbo"` explicitly,
change it before 2026-10-23.
