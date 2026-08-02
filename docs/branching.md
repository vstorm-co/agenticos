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

Dependabot batches monthly, with the agent frameworks on their own weekly
schedule — they move fast and this codebase is meant to track them.

Two things about it are not obvious:

- **Group patterns must carry a trailing `*` to match a dependency written with
  extras.** `pydantic-ai-slim[openrouter,…]` is not matched by
  `pydantic-ai-slim`. That silence cost months: the `agent-frameworks` group
  never opened a single pull request, and the runtime rode in
  `backend-everything-else` with its majors.
- **Dependabot cannot update `frontend/bun.lock`.** Its npm ecosystem does not
  know bun's lockfile, so a frontend bump arrives as `package.json` alone and
  `bun install --frozen-lockfile` refuses the mismatch.
  `.github/workflows/bun-lock-sync.yml` regenerates it on the pull request.

## Reviews

The [automated reviewer](code-review.md) runs on every pull request. It is never
a required check, so it cannot fail a build — but its findings are review
threads, and the ruleset above requires those resolved. Replying is not enough —
somebody has to mark the thread resolved before the merge button comes back. See
[code-review.md](code-review.md).
