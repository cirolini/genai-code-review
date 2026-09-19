# Changelog

## Unreleased

### Added

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
