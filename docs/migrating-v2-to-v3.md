# Migrating from v2 to v3

**Short version: you do not have to change anything.** Every v2 input still
works. If you point `@v2` at `@v3` and change nothing else, the action behaves
as it did before.

That is deliberate. Everything new in v3 is opt-in.

---

## If you change nothing

```yaml
- uses: cirolini/genai-code-review@v3
  with:
    openai_api_key: ${{ secrets.OPENAI_API_KEY }}
    github_token: ${{ secrets.GITHUB_TOKEN }}
    github_pr_id: ${{ github.event.number }}
    mode: files
```

This keeps working. `openai_api_key`, `openai_model`, `openai_temperature` and
`openai_max_tokens` are read whenever their v3 equivalents are unset, and
`mode: files` and `mode: patch` still produce one summary comment, exactly as in
v2.

The one thing you should check: if you pinned `openai_model: "gpt-3.5-turbo"`
explicitly, change it. That model loses API access on 2026-10-23. The default is
now `gpt-5.6-luna`, which costs less than `gpt-3.5-turbo` did on both input and
output tokens.

---

## Getting the v3 behaviour

Add `mode: review`:

```yaml
- uses: cirolini/genai-code-review@v3
  with:
    api_key: ${{ secrets.OPENAI_API_KEY }}
    github_token: ${{ secrets.GITHUB_TOKEN }}
    github_pr_id: ${{ github.event.number }}
    mode: review
```

That changes the output shape:

| | v2 (`mode: files` / `patch`) | v3 (`mode: review`) |
|---|---|---|
| Output | one long comment | inline comments on the diff lines, grouped into one review |
| On a new push | a new comment each time | one summary comment, edited in place |
| Scope on a push | the whole pull request again | only the commits since the last review |
| Volume | everything the model said | the top `max_comments` (default 5), the rest counted and listed |
| Large diffs | silently truncated by the provider | chunked, with anything that did not fit reported |
| Lockfiles, generated code | sent to the model | skipped by default |

`mode` still defaults to `files`, so this is something you turn on rather than
something that happens to you.

---

## Input renames

Old inputs still work. New names are clearer, and are the only way to reach a
non-OpenAI provider.

| v2 input | v3 input | Notes |
|---|---|---|
| `openai_api_key` | `api_key` | Now the key for whichever provider you chose |
| `openai_model` | `model` | |
| `openai_temperature` | `temperature` | |
| `openai_max_tokens` | `max_tokens` | |
| — | `provider` | `openai`, `anthropic`, `gemini`, `openai-compatible` |
| — | `base_url` | For `openai-compatible` servers |

If both are set, the v3 input wins.

---

## New inputs

All optional.

| Input | Default | What it does |
|---|---|---|
| `max_comments` | `5` | Inline comments per review; the rest are counted and listed |
| `min_severity` | `nit` | Lowest severity worth posting |
| `min_confidence` | `0` | Lowest confidence worth posting |
| `ignore_paths` | sensible defaults | Globs to skip |
| `incremental` | `true` | On a push, review only the new commits |
| `panel` | — | Experimental: two providers merged, ~2x cost |
| `config_path` | `.genai-review.yml` | Repository config file |
| `runlog_path` | `genai-review-runlog.json` | Per-run JSON log |

---

## Two things to fix while you are here

Both were wrong in the v2 documentation, and both cost people working setups.

**1. Add the `permissions` block.** It was missing from the v2 example. Without
`pull-requests: write`, the action authenticates, reads your pull request, and
then silently fails to post — which looks like the action not working at all.

```yaml
permissions:
  contents: read
  pull-requests: write
```

**2. Remove `actions/checkout`.** It was in some v2 examples and was never
needed: the action reads the pull request over the API. Worse, in this
repository's own workflow it masked the bug that made `v2` unusable everywhere
else — see [issue #47](https://github.com/cirolini/genai-code-review/issues/47).

There was also an `openai_engine` input in the v2 documentation. The action
never read it; the correct name has always been `openai_model`.

---

## Moving to another provider

```yaml
- uses: cirolini/genai-code-review@v3
  with:
    provider: anthropic
    api_key: ${{ secrets.ANTHROPIC_API_KEY }}
    github_token: ${{ secrets.GITHUB_TOKEN }}
    github_pr_id: ${{ github.event.number }}
    mode: review
```

Or a model you host yourself:

```yaml
    provider: openai-compatible
    base_url: http://localhost:11434/v1
    model: llama3
```

---

## Coming from the `dlidstrom` fork

[`dlidstrom/genai-code-review`](https://github.com/dlidstrom/genai-code-review)
kept this action working while this repository was unmaintained, and published
its own `v3.0.x` releases. **Its version numbers and this repository's are not
aligned** — `cirolini/genai-code-review@v3` is not a successor to
`dlidstrom/genai-code-review@v3.0.8`.

Its `github_base_url` input is covered here by the standard `GITHUB_API_URL`
environment variable, which GitHub Enterprise runners set automatically, so no
input is needed. Its `include_regex` / `exclude_regex` correspond to
`ignore_paths`, which takes globs rather than regular expressions.

If the fork works for you, there is no urgency in switching.

---

## If something breaks

Open an issue with the workflow file and the run log. The action writes a
`genai-review-runlog.json` containing the provider, model, token counts,
coverage and what was suppressed — and no credentials, diff or source code, so
it is safe to attach.
