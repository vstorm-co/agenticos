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

Three of those six do not run on every pull request. `test`, `test-frontend` and
`e2e` are 8.2, 5.3 and 5.1 billed minutes each, and a `changes` job decides which
of them a change set can provably not affect — `scripts/ci_changed_scope.py`, so
the rule is testable rather than a glob in a YAML file
([#317](https://github.com/vstorm-co/agenticos/issues/317)).

This is legal because GitHub satisfies a required status check with **`success`,
`skipped` or `neutral`**. It is why the gate is a job-level `if:` and **not** a
`paths:` filter on the workflow: a filtered-out workflow never posts its checks at
all, so the ruleset waits for six contexts that will never arrive and the merge
button stays grey forever.

The classifier is written the timid way round — **a job is skipped only when every
changed path is provably irrelevant to it**, so an unrecognised path runs
everything. The permissive spelling of the same idea would let a new directory
silently stop a suite from running, which is not a red build but a green one with a
gate missing from it, and this repository has already paid for that twice (#143,
#165). Only two exemptions exist, both checked rather than assumed: `docs/**`,
`mkdocs.yml` and a top-level `*.md` (no test reads any of them), and the opposite
half of the tree for each of the two unit suites. `e2e` is exempted from neither
half. `lint` is never gated at all, because `make lint-spelling` is the only thing
that reads every tracked file.

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

### One run per branch

`ci.yml` carries a concurrency group keyed on `github.ref`, so pushing again to a
branch cancels its previous run. That matters because `CLAUDE.md` asks for a commit
and a push per finished piece: with nothing cancelling, 75 of the 369 runs in the
first six days of August were superseded while still in flight — about 1,800 billed
minutes answering questions about commits nobody was waiting on.

**A push to `main` is exempt, and the way it is exempted is the interesting part.**
The merge's own run is what makes the history and the badge mean anything, so a
`main` run must neither be cancelled nor queued. `cancel-in-progress: false` gives
only the first of those: `false` means *queue*, and GitHub cancels any previously
**pending** run in a group when a newer one is queued. With a single group for
`main`, merge A running and B pending, C landing would cancel B outright and B's
commit would get no CI at all — at fourteen releases in six days against a ~10
minute `main` run, two merges inside one window is not a rare shape.

So the group carries `github.run_id` on a push, which is unique per run: every
merge gets a group of its own and collides with nothing. Pull requests all resolve
to the same suffix and go on cancelling each other per `github.ref`.

## Squash, and why the pull request title matters

`main` keeps one commit per pull request, built from the **pull request title and
body** rather than from the branch's own commits. So `wip`, `fixup` and `try
again` never reach it — and the description is not a courtesy, it is the commit
message that survives. `CLAUDE.md` has the format.

## The escape hatch

There are **no bypass actors**. An owner who needs to merge something now
disables the ruleset, merges, and turns it back on. That is deliberate: a bypass
that is always available is a bypass that gets used weekly, and a release path
nobody can describe. Three clicks and an audit entry is the right amount of
friction for something that should be rare.

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
  `backend-everything-else` with its majors. Equally, `fastapi` stays exact —
  `fastapi*` would drag in `fastapi-cache2`.
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
