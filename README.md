# GenAI Code Review

A GitHub Action that reviews pull request diffs with an LLM and posts inline
comments. It works with OpenAI, Anthropic, Google Gemini, or any
OpenAI-compatible server.

Unlike most such tools, it is built around a comment budget: it posts only the
few findings most worth a human's attention, and tells you what it held back.

---

## Quick start

One workflow file. Nothing else.

```yaml
# .github/workflows/code-review.yml
on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: cirolini/genai-code-review@v3
        with:
          api_key: ${{ secrets.GEMINI_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          github_pr_id: ${{ github.event.number }}
```

No `actions/checkout` step is needed — the action reads the pull request over
the API and never uses the repository on disk.

The `permissions` block is required. Without `pull-requests: write` the action
authenticates, reads your pull request, and then silently fails to post.

---

## Why a comment budget

AI made writing code cheap. It did not make reviewing it cheap. The bottleneck
moved from the person writing to the person reading, and that person's attention
is now the scarce resource on the team.

A review bot that posts forty comments does not add forty units of value. It
spends forty units of somebody's attention, and it usually returns less than the
best five comments would have. Worse, it trains the reviewer to skim past the
bot entirely — at which point the two comments that actually mattered are lost
along with the thirty-eight that did not.

So this one is given a budget and made to choose:

- **`max_comments`** (default 5) — findings are ranked by severity, with
  confidence ordering within a severity, and only the top few are posted.
- **Nothing is silently dropped.** The summary says how many findings were held
  back, lists them, and names the setting to change to see them. A reviewer who
  knows twelve minor findings were suppressed can ask for them; one who was
  never told has been quietly misled about coverage.
- **Repeat findings do not consume budget.** A finding already raised on an
  earlier push is filtered out *before* ranking, so it cannot push a new finding
  out of the budget.
- **The summary says what was not reviewed** — ignored files, files too large
  for one request, truncated diffs, and the fact that an incremental run only
  looked at recent commits. This is the section most tools leave out, and it is
  the one that decides whether silence from the bot can be trusted.

The same idea drives the rest of the design: one sticky summary comment edited
in place rather than a new one per push, one grouped review rather than N
separate notifications, and lockfiles and generated code dropped before they
ever reach the model.

Whether this actually produces better reviews is a measurable question, not a
claim. See [`docs/results/`](docs/results/) for the harness and
[`docs/case-study.md`](docs/case-study.md) for the reasoning.

---

## Providers

| `provider` | Default model | Key read from |
|---|---|---|
| `gemini` (default) | `gemini-3.8-flash` | `api_key`, else `GEMINI_API_KEY` |
| `openai` | `gpt-5.6-luna` | `api_key`, else `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-5` | `api_key`, else `ANTHROPIC_API_KEY` |
| `openai-compatible` | none — `model` is required | `api_key`, optional |

Defaults are cost-conscious rather than each vendor's strongest model, because
this runs on every push to every pull request and the bill is yours. Set `model`
to pick a different one.

`gemini` is the default because it is the configuration with measured numbers
behind it: 100% precision and 0% noise on the eval set, at $0.0009 per pull
request. See [`docs/results/`](docs/results/).

A workflow that passes the deprecated `openai_api_key` and does not set
`provider` stays on OpenAI, so moving the default cannot send an OpenAI key to
Google.

```yaml
- uses: cirolini/genai-code-review@v3
  with:
    provider: anthropic
    api_key: ${{ secrets.ANTHROPIC_API_KEY }}
    github_token: ${{ secrets.GITHUB_TOKEN }}
    github_pr_id: ${{ github.event.number }}
```

### Panel mode (experimental, off by default)

`panel` runs two providers over the same diff and merges what they found. A
finding both reported has its confidence raised by 15%; one only a single
member reported has it cut by 30%, so it is demoted rather than discarded — a
model spotting a real blocker the other missed is still worth keeping. Findings
are matched across members by file, category and normalised title, because two
models describing one defect rarely agree on the line or the wording. The
summary reports the agreement rate.

```yaml
- uses: cirolini/genai-code-review@v3
  with:
    panel: gemini,anthropic
    api_key: ${{ secrets.GEMINI_API_KEY }}
    github_token: ${{ secrets.GITHUB_TOKEN }}
    github_pr_id: ${{ github.event.number }}
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

**Every member needs its own key.** The `api_key` input goes to the first
member only; the others read their provider's environment variable
(`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`). Without it the run fails at startup
with `provider ... needs an API key` rather than quietly reviewing with one
model.

**OpenAI cannot currently be the second member.** The action declares
`OPENAI_API_KEY` from its own deprecated input, so a value passed through the
step's `env:` is overwritten with an empty one and the member fails to build.
Put OpenAI first, as `provider`/`api_key`, and the other model second.

**The price is roughly double** — two requests, two sets of tokens, and the
latency of both. That is why it is off by default and called experimental:
there is no measurement yet showing the second opinion is worth what it costs.
Panel mode has never been run against two live providers. See
[`docs/results/`](docs/results/).

### Self-hosted and third-party endpoints

`openai-compatible` covers Ollama, vLLM, Azure OpenAI, OpenRouter, Together and
anything else exposing the same API. `api_key` is optional, so a local server
with no auth works:

```yaml
    provider: openai-compatible
    base_url: http://localhost:11434/v1
    model: llama3
```

---

## Configuration

Every setting can be given as an action input or in a `.genai-review.yml` file
at the repository root. **Action inputs take precedence** over the file, so a
workflow can always override the repository's defaults.

See [`.genai-review.yml.example`](.genai-review.yml.example) for a commented
file. There is deliberately no `api_key` key in it: credentials belong in a
secret.

### Reference

| Input | Default | What it does |
|---|---|---|
| `github_token` | — | **Required.** Usually `${{ secrets.GITHUB_TOKEN }}` |
| `github_pr_id` | — | **Required.** Usually `${{ github.event.number }}` |
| `api_key` | — | Key for the chosen provider |
| `provider` | `gemini` | `gemini`, `openai`, `anthropic`, `openai-compatible` |
| `model` | per provider | Model ID |
| `base_url` | — | Required for `openai-compatible` |
| `mode` | `review` | `review` posts inline comments; `files`/`patch` are v2 behaviour |
| `max_comments` | `5` | Inline comments per review; the rest are counted and listed |
| `min_severity` | `nit` | `blocker`, `major`, `minor`, `nit` |
| `min_confidence` | `0` | 0 to 1 |
| `ignore_paths` | see below | Globs to skip. Unset uses the defaults |
| `incremental` | `true` | On a push, review only the new commits |
| `panel` | — | Experimental. Two providers, merged. ~2x cost — [details](#panel-mode-experimental-off-by-default) |
| `language` | `en` | Language the findings are written in |
| `custom_prompt` | — | Extra instructions for the reviewer |
| `temperature` | `0.5` | Sampling temperature |
| `max_tokens` | `2048` | Response length cap |
| `config_path` | `.genai-review.yml` | Repository config file |
| `runlog_path` | `genai-review-runlog.json` | Where the per-run JSON log is written |

`ignore_paths` defaults to skipping lockfiles, vendored and generated code,
snapshots, migrations and minified assets — files nobody reviews by hand. Set it
to a single space to review everything.

### Deprecated inputs

`openai_api_key`, `openai_model`, `openai_temperature` and `openai_max_tokens`
still work and are used whenever their v3 equivalent is unset. A workflow
written for v2 runs on v3 unchanged. See the
[migration guide](docs/migrating-v2-to-v3.md).

---

## Security

**Permissions.** The action needs `contents: read` and `pull-requests: write`
and nothing more.

**Do not use `pull_request_target` for pull requests from forks.** That trigger
runs with a token that can write to your repository *and* with access to your
secrets, while the code being reviewed is controlled by whoever opened the pull
request. The ordinary `pull_request` trigger is correct here: forks get a
read-only token and no secrets, which is exactly what you want when the input is
untrusted. If reviews on fork pull requests matter to you, accept that they will
not run rather than reaching for `pull_request_target`.

**The diff is treated as untrusted data.** Code under review can contain text
aimed at the reviewer — "ignore previous instructions", a forged system message,
a comment claiming the change is pre-approved. The diff is fenced with a
randomly generated per-request sentinel it cannot forge, the real instructions
come after the data, and the model is told that an injection attempt is itself
worth reporting as a `security` finding. The bot never executes anything from a
diff; its only output is findings validated against a schema.

**API keys.** Pass them from a secret. The key is never written to the run log,
never included in an error message posted to a pull request, and never read from
`.genai-review.yml`.

**What leaves your repository.** The diff of the files being reviewed is sent to
whichever provider you configure. If that is not acceptable for a given
repository, use `ignore_paths` to exclude the sensitive parts, or point
`provider: openai-compatible` at a model you host yourself.

---

## Run logs

Every review writes a JSON file with provider, model, tokens, estimated cost,
latency, findings by severity, posted versus suppressed, and what was not
reviewed. Upload it to keep a record:

```yaml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: genai-review-runlog
          path: genai-review-runlog.json
```

It contains no credentials, no diff and no source code.

---

## How it works

1. Files matching `ignore_paths` are dropped before anything is sent.
2. On a push, only the commits since the last review are considered.
3. The remaining diff is chunked to fit the model's context, and anything that
   does not fit is reported rather than silently truncated.
4. The model returns findings matching a JSON schema — file, line range,
   severity, category, confidence, title, rationale, optional suggestion. Output
   that does not validate gets exactly one repair attempt.
5. Findings are checked against the diff. GitHub rejects an entire review if one
   comment points outside the diff, so findings that cannot be placed are
   reported in the summary instead of taking the review down with them.
6. The top `max_comments` are posted as one grouped review, and a single sticky
   summary comment is created or updated.

---

## Development

```bash
make install   # dependencies
make check     # ruff + pytest
make eval-dry  # list the eval fixtures without calling a provider
make eval      # run the eval set (needs an API key; costs money)
```

---

## Related work

[`dlidstrom/genai-code-review`](https://github.com/dlidstrom/genai-code-review)
is a fork that kept this action working for people while this repository sat
unmaintained for two years, and published releases under its own `v3.0.x` tags.
If you are using it today, it still works. That fork and this one are not
version-aligned; the tags here are independent of the ones there.

## License

MIT — see [LICENSE](LICENSE).

## Authors

- **Rafael Cirolini** — [cirolini](https://github.com/cirolini)
- **Glauber Borges** — [glauberborges](https://github.com/glauberborges)
