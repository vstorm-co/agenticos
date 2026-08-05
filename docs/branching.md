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
