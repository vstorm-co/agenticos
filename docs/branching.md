# Branches and what protects them

One long-lived branch.

```
feat/… fix/… ──pull request──▶ main
```

`main` is what a reader of this repository clones and what tags are cut from.
Everything reaching it does so as a squashed commit from a short-lived branch,
after CI has run on the pull request.

There is no `dev`. There was, briefly: work landed there and reached `main` in
release pull requests. At this size it bought a staging branch nobody needed and
cost a second place for every change to sit, so it was removed.

## What is enforced, and by what

| Rule | Enforced by |
|---|---|
| No direct push to `main` | Ruleset — a pull request is required |
| CI green before merge | Required status checks: `lint`, `test`, `test-frontend`, `e2e`, `docs`, `Security Scan` |
| Squash on merge | Ruleset — the only allowed merge method |
| Conversations resolved | Ruleset |
| Stale approvals dismissed on a new push | Ruleset |
| No force push, no deletion | Ruleset |
| No commit made while standing on `main` | `no-commit-to-branch` in `.pre-commit-config.yaml` |
| Spelling, across every tracked file | codespell — as a hook on the files a commit touches, and as `make lint-spelling` in CI's `lint` job over the whole tree |
| Routes hold only routers, no banner comments, no dead code | `check_routes.py`, `check_comments.py` and `vulture` — hooks in `.pre-commit-config.yaml` (each scans the whole tree, `pass_filenames: false`) and steps of `make lint-backend` in CI's `lint` job |
| No dependency declared that nothing imports | `deptry` — a step of `make lint-backend` in CI's `lint` job, gating on DEP002 and DEP004. Not a pre-commit hook: it reads the whole manifest against the whole tree, so there is no per-file version of the question |
| YAML formatting, workflow security, the pre-commit basics, across every tracked file | yamlfmt, zizmor and `pre-commit-hooks` (`end-of-file-fixer`, `trailing-whitespace`, `check-yaml/json/toml`, `detect-private-key` …) — as hooks on the files a commit touches, and as `make lint-precommit` in CI's `lint` job over the whole tree. Like spelling, these are per-file by nature, so a `rev:` bump that brings a new rule breaks every existing file with nothing noticing until an unrelated edit is refused by it |

A hook only ever reads what a commit touches, which makes it a poor gate on its
own: a misspelling that merges with its file sits there until somebody edits that
file for an unrelated reason, and their commit is refused by a word they did not
write. That is why the spelling check is in the table twice — the hook is the fast
feedback, `make lint-spelling` is what keeps the claim true for the tree.

The status checks are listed individually today. They should collapse into a
single aggregating `All Checks Passed` job, so that adding a CI job stops meaning
"remember to edit a ruleset" — a required-check list that drifts from the
workflow is how a build ends up passing on nothing.

### A required check may legitimately report `skipped`

!!! info "A `skipped` required check is a pass, not a problem"

    GitHub satisfies a required status check with `success`, `skipped` **or**
    `neutral`. So a backend-only branch gets no frontend answer at all - which
    means "green" on such a branch is a claim about fewer jobs than `make check`
    runs.

Three of those six do not run on every pull request. `test`, `test-frontend` and
`e2e` are 8.2, 5.3 and 5.1 billed minutes each, and a `changes` job decides which
of them a change set can provably not affect — `scripts/ci_changed_scope.py`, so
the rule is testable rather than a glob in a YAML file
([#317](https://github.com/vstorm-co/agenticos/issues/317)).

That is why the gate is a job-level `if:` and **not** a
`paths:` filter on the workflow: a filtered-out workflow never posts its checks at
all, so the ruleset waits for six contexts that will never arrive and the merge
button stays grey forever.

The classifier is written the timid way round: **a job is skipped only when every
changed path is provably irrelevant to it**, so an unrecognised path runs everything.

The permissive spelling of the same idea would let a new directory silently stop a
suite from running — which is not a red build but a green one with a gate missing
from it, and this repository has already paid for that twice (#143, #165).

Only two exemptions exist, both checked rather than assumed:

- `docs/**`, `mkdocs.yml` and a top-level `*.md`, because no test reads any of them;
- the opposite half of the tree, for each of the two unit suites.

`e2e` is exempted from neither half, and `lint` is never gated at all — because
`make lint-spelling` and `make lint-precommit` read every tracked file.

The second exemption stops short of one directory. `frontend/src/app/api/**` is
the BFF, and `backend/tests/api/test_bff_forwarded_paths.py` checks the
`/api/v1/…` paths those handlers hard-code against the backend's own route table
— so a change to a proxy runs the backend suite too. Skipping it there would be
the same green-with-a-gate-missing failure as above, on the one test written to
catch it.

Two details the timid direction needs in order to actually hold, both of which the
first version of this got wrong:

- Each gated job carries `!cancelled()` alongside the output check. Without it, a
  `changes` job that **failed** — a 502 from the API, a rate limit — would skip all
  three suites without their conditions ever being read, and since `changes` is not
  itself a required context, the merge button would go green over a branch where no
  suite ran.
- The job feeds `previous_filename` in as well as `filename`. A rename reports only
  the path it arrived at, so a module moved out of `backend/` would otherwise be one
  frontend path and skip the backend suite for a change that deleted a backend
  module.

What a change set skips is printed in the `changes` job's log. Locally nothing is
skipped: `make check` runs the whole set.

### A stacked pull request runs CI too

Two branches that edit the same file are told to stack — the second is opened
against the first rather than against `main` — so `ci.yml`'s `pull_request` trigger
carries **no `branches:` filter**. That filter matches on the *base*, and while it
was there a stacked pull request matched no trigger and ran nothing at all
([#359](https://github.com/vstorm-co/agenticos/issues/359)).

The dangerous half was not the missing run, it was how it read. A pull request with
no jobs shows an **empty** checks list, not a red one: `gh pr checks` answers "no
checks reported" and the rollup is empty, which looks like a run that has not started
yet. Four pull requests merged that way in one day, each verified only on a laptop.
Nothing closed the gap until the child was retargeted to `main` after its parent
merged, which is precisely when nobody waits for a fresh seven-minute run.

It costs little: the `changes` job classifies a stacked child on its own diff — it
reads `pulls/{n}/files`, which is the comparison against that pull request's own base
— and the concurrency group below cancels the child's superseded runs like any
other's.

That the trigger carries no base filter is asserted rather than assumed, in
`backend/tests/test_ci_workflow.py`. It has to be: a workflow that does not trigger
produces no evidence that it did not, so nothing about a run can reveal the
regression. The same file asserts the other property no run can show — that every
job bounds its own runtime, below.

Two limits worth stating plainly. **A green stacked pull request was checked against
its parent, not against `main`** — checks belong to a head commit, so retargeting
carries the old result forward unchanged; that is inherent to stacking rather than
something a trigger can fix, and it is a reason to keep stacks short. And **CodeQL is
not configured here**: it runs from GitHub's default setup, whose triggers are not in
this repository, so whether it reads a stacked pull request is not ours to decide.

### Every job bounds its own runtime

`changes` was the only job in `ci.yml` carrying a `timeout-minutes`, so the other
seven inherited GitHub's default of **360 minutes**
([#364](https://github.com/vstorm-co/agenticos/issues/364)), so a stalled job would
have held its required status check for six hours with nothing in this repository
ending it sooner. That was written as a precaution against something nobody had
seen. Fourteen `e2e` runs hit the bound in the four days to 18 August
([#879](https://github.com/vstorm-co/agenticos/issues/879)) — and what a job looks
like when it does is below.

| Job | Bound | Observed |
|---|---|---|
| `changes` | 5 | 7s |
| `lint` | 10 | 22s |
| `Security Scan` | 10 | 14s |
| `docs` | 15 | 4m34s |
| `test-frontend` | 20 | 5m08s |
| `docker` | 20 | 2m30s |
| `test` | 25 | 7m43s |
| `e2e` | 25 | 8m01s |

Observed times are from run 31116003994, a full matrix on `main`. Each bound is
several times its job rather than just above it: the timeout exists to end a stall,
and one tight enough to trim a legitimately cold cache is a red build for a reason
unrelated to the diff.

### One run per branch

`ci.yml` carries a concurrency group keyed on `github.ref`, so pushing again to a
branch cancels its previous run. That matters because `CLAUDE.md` asks for a commit
and a push per finished piece: with nothing cancelling, 75 of the 369 runs in the
first six days of August were superseded while still in flight — about 1,800 billed
minutes answering questions about commits nobody was waiting on.

**A push to `main` is exempt, and the way it is exempted is the interesting part.**

The merge's own run is what makes the history and the badge mean anything, so a
`main` run must neither be cancelled nor queued.

`cancel-in-progress: false` gives only the first of those. `false` means *queue*, and
GitHub cancels any previously **pending** run in a group when a newer one is queued.

With a single group for `main` — merge A running, B pending — C landing would cancel
B outright, and B's commit would get no CI at all. At fourteen releases in six days
against a ~10 minute `main` run, two merges inside one window is not a rare shape.

So the group carries `github.run_id` on a push, which is unique per run: every
merge gets a group of its own and collides with nothing. Pull requests all resolve
to the same suffix and go on cancelling each other per `github.ref`.

### Two things report `cancelled`, and only one of them is that

The section above is the cancellation that is working as designed, and it is the
explanation everybody reaches for. **The other one is a job that ran out of its
`timeout-minutes`** — GitHub records a job it ended on the bound as `cancelled`,
not as a failure — and a `cancelled` required check is *not* treated as a pass the
way a `skipped` one is, so the merge stays blocked on a diff that is fine.

Telling them apart takes one look:

| | Superseded (#317) | Ended on its bound (#879) |
|---|---|---|
| What else is in the run | every in-flight job cancelled together | **one** job; the rest are green |
| The run's own conclusion | `cancelled` | `success`, less the one job |
| Duration of the cancelled job | whatever it had reached | its `timeout-minutes`, to the second |
| A newer push on the branch | yes — that is the cause | no |
| The log's last line | `The operation was canceled.` | the same line, which is the trap |

The duration is the tell. `gh api repos/vstorm-co/agenticos/actions/runs/<id>/attempts/<n>/jobs`
gives `started_at`, `completed_at` and per-step conclusions — **and it must be the
`attempts/<n>` form**, because a re-run rewrites what the plain `runs/<id>/jobs`
endpoint answers, so a job re-run into the green reports `success` there and the
original conclusion is gone.

What the fourteen had in common was one step: `playwright install --with-deps`
shelling out to `apt-get`, which stalls unbounded when the runner's Azure mirror is
unreachable. The e2e job no longer installs system packages at all, and
`backend/tests/test_ci_workflow.py` refuses a step that would. The general lesson
outlives that step, though: **a step reaching a third party is a step that can hang
without a bound of its own**, and one that does spends the job's whole budget and
then reports as somebody else's cancellation.

## Squash, and why the pull request title matters

!!! important "The pull request description *is* the commit message that survives"

    `main` keeps one commit per pull request, built from the title and body rather
    than from the branch's own commits. `CLAUDE.md` has the format.

So `wip`, `fixup` and `try again` never reach it — and the description is not a
courtesy.

## The escape hatch

!!! warning "There are no bypass actors"

    An owner who needs to merge something now disables the ruleset, merges, and
    turns it back on - three clicks and an audit entry, which is the right amount
    of friction for something that should be rare.

That is deliberate: a bypass that is always available is a bypass that gets used
weekly, and a release path nobody can describe.

## Dependency updates

The backend runs weekly, with the agent frameworks grouped apart from everything
else — they move fast and this codebase is meant to track them. The frontend
runs monthly, after a seven-day cooldown.

Dependabot proposes updates for **direct** dependencies. Everything under them
moves only when a direct one drags it along, which is why
`.github/workflows/dependency-freshness.yml` exists: once a week it upgrades the
entire lock — transitive packages included — runs the whole suite against it,
and opens an issue if that breaks. Nothing is committed; the upgrade is thrown
away with the runner. `make deps-upgrade-all` is the same thing locally, and is
how a red issue from it reproduces.

Two things about it are not obvious, and both cost time before they were
understood:

- **A group pattern must carry a trailing `*` to match a dependency written with
  extras.** `pydantic-ai-slim[openrouter,…]` is not matched by
  `pydantic-ai-slim`. That silence cost months: the `agent-frameworks` group
  never opened a single pull request, and the runtime rode in
  `backend-everything-else` with its majors. Conversely `fastapi` stays exact
  because it is declared without extras and needs no wildcard; it used to need
  to avoid one, since `fastapi*` also caught `fastapi-cache2`, until that
  dependency was removed in #155.
- **Dependabot cannot update `frontend/bun.lock`.** Its npm ecosystem knows
  `package-lock.json`, `yarn.lock` and `pnpm-lock.yaml`, and not bun's. So a
  frontend bump arrives as `package.json` alone and `bun install
  --frozen-lockfile` refuses the mismatch, turning `test-frontend` and `e2e` red
  for a reason unrelated to the dependency. **Regenerate it by hand** on the
  pull request branch:

  ```bash
  cd frontend && bun install --lockfile-only && git commit -am "build(deps): sync bun.lock"
  ```

  Automating that is harder than it looks: a workflow on `pull_request` gets a
  read-only token when Dependabot triggered it, whatever its `permissions` block
  says, so it cannot push the result back.

## Reviews

The [automated reviewer](code-review.md) runs on every pull request. It is never
a required check, so it cannot fail a build — but its findings are review
threads, and the ruleset above requires those resolved. Replying is not enough —
somebody has to mark the thread resolved before the merge button comes back. See
[code-review.md](code-review.md).

CodeQL's quality half opens threads on the same terms, as
`github-code-quality[bot]`. It cannot be filtered by rule or by path — the only
switch is off, for a whole language, which is not a trade worth making —
so [code-review.md](code-review.md#codeql-and-the-findings-that-block-a-merge)
lists the findings already adjudicated instead, and resolving one of those costs a
click rather than an essay.
