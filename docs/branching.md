# Branches and what protects them

Two long-lived branches, and one direction of travel.

```
feat/… fix/… ──▶ dev ──▶ main
```

`dev` is where work lands. `main` is what a reader of this repository clones, so
everything reaching it has already been through `dev`, where CI and the E2E
journey run on every pull request.

The [automated reviewer](code-review.md) runs there too, and again on the release
pull request — but it is advisory, and a commit pushed straight to `dev` skips it
entirely. This is a gate on provenance and on CI, not on review.

## What is enforced, and by what

| Rule | On | Enforced by |
|---|---|---|
| No direct push | `main` | Ruleset — a pull request is required |
| A pull request may only come from `dev` | `main` | The `Source branch is dev` check, required |
| CI green before merge | `main` | Required status checks |
| No force push, no deletion | `main`, `dev` | Ruleset |
| No commit made while on `main` | local | `no-commit-to-branch` in `.pre-commit-config.yaml` |

`dev` itself takes direct pushes. Blocking them would only teach everybody
`--no-verify`, and the branch it protects is the next one along.

## Why the source-branch rule is a workflow

A ruleset can require a pull request, an approval and a green build. It cannot
say **which branch the pull request may come from** — so that half lives in
`.github/workflows/branch-policy.yml`, wired in as a required status check.
A pull request into `main` from anything other than this repository's `dev`
fails it, and the merge button stays disabled.

It also refuses a fork whose branch happens to be called `dev`. Same name,
different history, and none of it has been through this repository.

## The escape hatch

There are **no bypass actors**. An owner who needs to merge something now
disables the ruleset, merges, and turns it back on. That is deliberate: a
bypass that is always available is a bypass that gets used weekly, and a
release path nobody can describe. Three clicks and an audit entry is the right
amount of friction for something that should be rare.

## Releasing

One pull request, `dev` into `main`, carrying everything that is ready.

```bash
gh pr create --base main --head dev --title "chore: release" --body "…"
```

The reviewer runs on it like any other pull request, and CI runs the full
matrix. Nothing else opens against `main`.
