# Rebuilding a code review bot around the reviewer's attention

I wrote this GitHub Action in 2023. It sent a pull request's changed files to
OpenAI and posted one long comment. It picked up 369 stars, 70 forks and about
120 repositories using it — and then I did not touch it for two years.

When I came back to it, two things were true. The action was completely broken,
and the problem it was built to solve had changed shape.

This is what I did about both.

---

## Part 1: it had been broken the whole time

The first thing I found was not a design flaw. It was that `v2` could not start
on anybody's repository except this one.

GitHub runs container actions with `--workdir /github/workspace`, which
overrides the `WORKDIR` in the image. The entrypoint was relative:

```dockerfile
CMD ["python", "src/main.py"]
```

So it resolved against the *caller's* checked-out repository, not the action's
own code, and died with `can't open file '/github/workspace/src/main.py'`.

It shipped and survived two years for a reason worth sitting with: this
repository's own demo workflow ran `actions/checkout` before calling the action.
That put a `src/main.py` on the container's working directory, so the action
passed its own tests here while failing everywhere else.

**The test suite was green because it was testing the wrong file.**

I removed the checkout — it was never needed, since the action reads the pull
request over the API — and the bug reproduced immediately in this repository for
the first time. Then I added a CI job that builds the image and runs it with the
same `--workdir` GitHub uses, asserting the interpreter reaches `main()` rather
than failing to open the file.

There was a second, independent break. `openai` was pinned to `1.30.1` but
`httpx` was not pinned at all. `httpx` 0.28 removed the `proxies` argument that
`openai` 1.30 passes, so any fresh build failed at client construction. Pinning
a direct dependency while leaving its transitive dependencies floating is a way
to be surprised later, and I was.

Both fixes went out as `v2.1`, with `v2` moved to it so the existing users got
the fix without editing anything. The one-line entrypoint fix had been sitting
in an unmerged pull request from `@arjunsuresh` for a year.

### What I would tell myself in 2023

Test the artifact you ship, in the environment you ship it to. A test suite that
runs your source from a different path than production does is not testing your
deployment; it is testing your imports.

---

## Part 2: the problem changed

When I wrote this, the interesting question was "can a model say anything useful
about a diff?" That question is settled. The interesting question now is what to
do with the fact that it can say a great deal.

AI made writing code cheap. It did not make reviewing it cheap. The bottleneck
moved from the person writing to the person reading — and *that* person's
attention is now the scarce resource on a team.

Which means a review bot that posts forty comments is not adding forty units of
value. It is spending forty units of somebody's attention. And it usually
returns less than the best five comments would have, because past a certain
volume the reviewer stops reading the bot at all — at which point the two
comments that mattered are lost along with the thirty-eight that did not.

So the design question for v3 was not "how do we find more problems?" It was
**"how do we spend the reviewer's attention well?"** Every decision below
answers that, and the constraint on all of them is the same: reduce the load on
the human *without hiding a real problem*.

---

## Design decisions

### 1. A comment budget, with the suppressed findings reported

**Decision.** Post at most `max_comments` inline comments (default 5). Rank by
severity, with confidence ordering within a severity. Count everything that did
not make the cut, list it in the summary, and name the setting to raise.

**Why.** The ranking puts severity above confidence deliberately: the cost of
missing a blocker the model is half sure about is much higher than the cost of
missing a nit it is certain of. Confidence does useful work *within* a severity,
ordering equals — it is a comparative signal, not a calibrated probability, and
treating it as one would be overreach.

The reporting half matters as much as the budget. A bot that quietly drops
findings is worse than one that posts them all, because the reviewer cannot tell
the difference between "nothing else was found" and "a lot else was found and
withheld". Saying "6 findings not posted" preserves the reviewer's ability to
decide.

**Cost.** If the ranking is bad, the budget hides real problems. This is the
riskiest decision in the project and the main thing the eval set exists to
check.

### 2. One sticky comment, and the state lives inside it

**Decision.** One summary comment per pull request, edited in place. The last
reviewed SHA and the fingerprints of findings already posted are stored in an
HTML comment inside its body.

**Why.** v2 posted a new comment on every push, so a pull request with eight
pushes carried eight stale reviews and sent eight notifications.

Incremental review needs to know what happened last time, and this project has a
hard constraint: no database, no hosted service, nothing to operate. The pull
request itself turns out to be adequate storage. An HTML comment is invisible
when rendered, durable, and readable in one API call.

Unreadable state degrades to a first run rather than raising. Somebody editing
the comment by hand should cost a duplicated comment, not a failed check.

**Cost.** The state is visible to anyone who views the comment's source, so it
cannot hold anything sensitive. It holds finding fingerprints and a SHA.

### 3. Fingerprints deliberately exclude line numbers

**Decision.** A finding's identity across runs is `file:category:normalised
title`.

**Why.** This is the detail I would have got wrong without thinking about it. A
later push that adds an import at the top of a file shifts every line below it.
If line numbers were part of the identity, the bot would re-post every existing
comment on every push that touched the top of a file — the exact noise the whole
phase exists to remove.

**Cost.** Two genuinely different problems in one file that happen to share a
category and a near-identical title would be merged. In practice the title
carries enough signal; in principle this is a known limit.

### 4. Findings are placed against the diff before posting

**Decision.** Parse the diff, determine which `(file, line)` pairs can carry a
comment, and filter findings against that. Snap a finding within three lines of
a real diff line; reject anything further and report it.

**Why.** GitHub rejects **the entire review**, not the offending comment, when
one comment points at a line outside the diff. So a single confused finding
would silence every good finding alongside it. That failure mode is invisible —
you get an API error in a log nobody reads and no comments on the pull request.

The snapping threshold is a judgement call. Models miscount by one or two,
usually counting from the hunk header; discarding those would lose real defects.
Twenty lines out means the model is not describing the line it thinks it is, and
snapping there would attach a confident comment to unrelated code.

### 5. The diff is untrusted input

**Decision.** Fence the diff with a randomly generated per-request sentinel, put
the real instructions *after* the data, and tell the model that injection
attempts are themselves reportable as `security` findings.

**Why.** Code under review can contain text addressed at the reviewer. A fixed
` ``` ` fence is trivially escaped by a diff containing ` ``` `. A random
sentinel cannot be predicted by the content it wraps.

Instructions come last because the end of the prompt is the strongest position,
and "whatever the diff happened to end with" should not occupy it.

**Cost.** None of this is a guarantee. It raises the cost of an attack; it does
not eliminate it. The real mitigation is that the bot's only output is
schema-validated findings — it has no capability to misuse.

### 6. Drop files nobody reviews by hand

**Decision.** Skip lockfiles, generated code, vendored dependencies, snapshots,
migrations and minified assets by default.

**Why.** These are the bulk of many diffs and almost never the part a human
needs. Sending them costs tokens and, worse, gives the model more surface on
which to find things to say.

**Cost.** A generated file *can* contain a real problem. The summary always
reports how many files were skipped, so the reviewer knows the coverage is
partial.

A small thing worth recording: the obvious glob, `**/package-lock.json`, does
not match a root-level `package-lock.json` under `fnmatch`, because there is
nothing before the slash. That is exactly where the file usually lives. A test
caught it; reading the code would not have.

### 7. Say what was not reviewed

**Decision.** The summary has a "Not reviewed" section: ignored files, files too
large for one request, truncated diffs, and the scope of an incremental run.

**Why.** This is the section most tools leave out, and I think it is the one
that decides whether the bot is trustworthy. Silence from a review bot is
ambiguous: it means either "I looked and found nothing" or "I did not look".
Those are completely different pieces of information and a reviewer acts on them
differently.

Everything else here reduces what the reviewer has to read. This is the
counterweight that keeps that from becoming deception.

### 8. Panel mode, as an experiment rather than a feature

**Decision.** Optionally run two providers, merge the findings, promote what
both reported and demote what only one did. Off by default.

**Why.** The hypothesis is that agreement between independent models is evidence
a finding is real, and disagreement is evidence it is taste. If that holds, the
comment budget can be spent on findings that survived a second opinion.

**Cost.** Roughly double the tokens and double the latency for one review. That
is a real price, and I am not going to recommend paying it on a hypothesis. It
stays off until the eval numbers say something.

---

## Measuring it

None of the above is worth anything as a claim. The eval set is the attempt to
make it checkable.

21 fixtures: 15 diffs with one seeded, labelled defect each — SQL injection,
off-by-one, missing null check, race condition, leaked credential, N+1 query,
missing test, command injection, path traversal, resource leak, swallowed
exception, integer division, weak hash, unbounded query, timezone bug — and 6
clean diffs where the correct behaviour is to say nothing.

The clean diffs are the important half. **Recall is the least interesting number
here.** A reviewer can live with a bot that misses something; they stop reading
a bot that wastes their time. So noise rate — how often a clean diff draws a
comment — is reported next to precision rather than buried.

Two scoring decisions:

- A finding within a few lines of the seeded line counts. Pointing at the call
  rather than the assignment two lines above is still finding it.
- Any plausible category counts. "SQL injection" is defensible as either
  `security` or `bug`, and penalising that would measure taxonomy agreement
  rather than detection.

Undefined metrics render as `n/a`, never `0%`. Reporting 0% precision for a run
that produced no findings would be a false claim rather than a neutral one.

### Results

**Not yet measured.** `docs/results/` is empty at the time of writing because
running the set needs API keys I had not wired up when the harness landed.

I am leaving this section honest rather than filling it with numbers from a stub
provider. In a case study about measurement, invented numbers would be worse
than none. `make eval PROVIDER=openai` produces the table; the two comparisons
that matter are budget on versus off, and single model versus panel.

---

## What I would do next

**Measure before adding anything.** The eval set exists and is unrun. Every idea
below is speculation until it has numbers next to it.

**Look at whether confidence is calibrated at all.** I use it as a tie-breaker
within a severity, which is defensible without calibration. If it turned out to
be well calibrated, it could do more work; if it turned out to be noise, the
ranking should drop it.

**Learn from what reviewers do with the comments.** Reactions and resolved
threads on the bot's comments are a free signal about which findings were worth
posting. That is the honest way to tune the budget — from what people accepted,
not from what I guessed.

**Reconsider the default mode.** `mode` still defaults to `files`, the v2
behaviour, because changing it would alter what existing workflows produce. The
v3 release is the right moment to flip it, as a documented change rather than a
silent one.

**Let severity thresholds vary by path.** A `blocker` in an auth module and a
`blocker` in a build script are not the same thing, and `min_severity` is
currently global.

---

## The thing I keep coming back to

The most useful change in this rewrite was not a model, a prompt or a provider
abstraction. It was deciding that the tool's job is to *withhold* most of what
it finds, and to be explicit about what it withheld.

That is an unusual thing to build. Every instinct in tooling pushes toward
surfacing more: more checks, more coverage, more signal. But the reviewer's
attention is a fixed budget that the tool is spending on their behalf, and a
tool that spends it carelessly gets ignored entirely — which is the worst
outcome available, because then it catches nothing at all.

A review bot's value is capped by how much of it a human will actually read.
