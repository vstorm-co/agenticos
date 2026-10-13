---
name: dev-agent
description: AI development agent. Opens a development branch and a stacked design branch up front, drives design and a general implementation plan to a reviewed, merged PR before any code exists, then — once merged — writes tests and the implementation on the development branch with review considered, without pushing. Portable across repos — detects the project's own test runner, source/test layout, branch naming and CI command rather than assuming one.
user-invocable: true
---

# dev-agent

## Usage

```
/dev-agent <requirements text> [--max-test-iterations N] [--max-impl-iterations N]
/dev-agent --resume
```

- `--max-test-iterations N` — review rounds for the test phase (default: 3)
- `--max-impl-iterations N` — review rounds for the implementation phase (default: 3)
- `--resume` — continue from the last checkpoint in `.dev-agent/state.json`

## Shape of the workflow

Two branches, two PRs, one hard human gate:

```
main ──▶ <dev-branch> (draft PR, open immediately) ──▶ <design-branch> (PR, design.md + implementation-plan.md)
                ▲                                              │
                └──────────────── merge, only once you say so ─┘
                │
                ▼ (local only, never pushed)
          tests → review → implementation → review
```

The design/plan PR is the only one this skill ever expects merged before it keeps going,
and it never decides that on its own — it always asks (§Phase 3). Everything after that
merge stays local: this skill does not push the development branch again and does not
open a third PR.

---

## Before the first phase — learn the repo

This skill runs in any repo, so nothing below is hardcoded. Before Phase 1, determine
and record (in `.dev-agent/state.json` under `repo_conventions`):

- **Default branch** — `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`,
  falling back to `git remote show origin | grep 'HEAD branch'`. Branch the development
  branch from this, not an assumed `main`.
- **Branch naming** — check recent branch names (`git branch -r`, or
  `gh pr list --state all --json headRefName --limit 30`) for the prefix vocabulary
  actually in use (`feat/`, `fix/`, `chore/`, or another scheme) and whether they embed
  an issue number. Match it for both branches this skill creates; default to `feat/` when
  nothing in the requirements suggests otherwise (a `fix`/`bug` framing → `fix/`).
- **Source/test layout** — where implementation and test files live (`src/` + `tests/`,
  `lib/` + `spec/`, a per-package layout, etc.). Look at the existing tree, not a
  convention from another project.
- **Test runner** — the actual command (`pytest`, `uv run pytest`, `npm test`,
  `go test ./...`, …). Check `package.json` scripts, `pyproject.toml`, a `Makefile`, or
  `CLAUDE.md`/`CONTRIBUTING.md`.
- **Aggregate pre-merge check** — the one command that gates a PR (commonly `make check`,
  `make ci`, `npm run verify`, `tox`). Look for it in the `Makefile`, `package.json`
  scripts, the CI workflow file, or the project's own contributor docs. If several exist
  (a fast one and a full one), prefer the one the repo's own docs say to run before a PR.
- **Testing conventions** — if the repo has its own testing skill, rule, or doc (grep
  `.claude/skills/*/SKILL.md`, `.claude/rules/`, `CONTRIBUTING.md`, `docs/testing.md`),
  read and follow it instead of generic advice. Otherwise fall back to standard TDD
  practice for the language: one behavior per test, deterministic fixtures, mock only at
  external boundaries.
- **Commit convention** — check `CLAUDE.md`/`CONTRIBUTING.md` and recent `git log` for the
  actual style (Conventional Commits is common but not universal) and match it instead of
  assuming `feat: …` / `test: …` verbatim.

Re-derive these on `--resume` too if `repo_conventions` is missing from an older
`state.json`.

---

## Workspace

All agent state lives in `.dev-agent/` (gitignored). The layout is:

```
.dev-agent/
  requirements.md
  design.md
  implementation-plan.md
  state.json
  review/
    tests/    round-{N}-issues.json  round-{N}-solutions.json
    impl/     round-{N}-issues.json  round-{N}-solutions.json
```

`state.json` schema:
```json
{
  "phase": "branches | design-plan | awaiting-design-merge | tests | review-tests | implementation | review-impl | done",
  "slug": "<kebab-case, derived from requirements>",
  "dev_branch": "<e.g. feat/<slug>>",
  "design_branch": "<e.g. feat/<slug>-design>",
  "dev_pr_url": "<set once the draft PR exists>",
  "design_pr_url": "<set once the design/plan PR exists>",
  "review_iteration": 0,
  "ci_fix_iteration": 0,
  "max_test_iterations": 3,
  "max_impl_iterations": 3,
  "requirements_hash": "<sha256 of requirements.md>",
  "last_checkpoint": "<ISO 8601>",
  "test_commit_sha": "<set at the end of Phase 5>",
  "repo_conventions": {
    "default_branch": "<detected>",
    "branch_prefix": "<detected>",
    "test_runner": "<detected command>",
    "ci_command": "<detected command>",
    "source_dir": "<detected path>",
    "test_dir": "<detected path>"
  }
}
```

---

## Steps

### 0. Initialise or resume

**New run** (`/dev-agent <requirements>`):
1. Parse `--max-test-iterations` and `--max-impl-iterations` from args (default both to 3).
2. Refuse to start with an unclean working tree (`git status --porcelain` non-empty) —
   ask the user to commit or stash first; this skill is about to create branches and must
   not carry someone else's uncommitted work onto them.
3. Create `.dev-agent/` if it does not exist.
4. Write the requirements text to `.dev-agent/requirements.md`.
5. Run the repo-discovery pass above and record `repo_conventions`.
6. Derive `slug`: a 3–6 word kebab-case summary of the requirements.
7. Compute `sha256` of the requirements file and write `state.json` with `phase=branches`,
   `slug`, all counters at 0, the parsed iteration limits, and `repo_conventions`.

**Resume** (`/dev-agent --resume`):
1. Read `.dev-agent/state.json`.
2. If it does not exist, tell the user there is nothing to resume.
3. If `requirements_hash` has changed since the checkpoint, warn the user: "Requirements changed since last checkpoint — continuing anyway. Use `/dev-agent <requirements>` to restart from scratch."
4. Ask: "Resume from phase **{phase}** (checkpoint: {last_checkpoint})? Or restart from scratch?" If the user chooses restart, delete `.dev-agent/` and re-run as a new run. Restarting from scratch does not touch or delete `dev_branch`/`design_branch` or their PRs — those are the user's now; say so.
5. If the working tree is not on `dev_branch` (or `design_branch`, while `phase` is still `branches`/`design-plan`/`awaiting-design-merge`), check out the branch the phase expects before doing anything else.
6. Jump to the step matching `state.json.phase`.

---

### Phase 1 — Branches and the draft PR

**Checkpoint**: set `phase=branches`.

1. Fetch and check out `repo_conventions.default_branch` at its latest commit
   (`git fetch origin <default_branch> && git checkout <default_branch> && git merge --ff-only origin/<default_branch>`).
2. Create the **development branch**, `dev_branch = <repo_conventions.branch_prefix><slug>`,
   from it: `git checkout -b <dev_branch>`.
3. Give it one commit that differs from `default_branch` — a new file,
   `.dev-agent-branch-marker.md`, one line: `Development branch for: <one-line requirements
   summary>.` (A branch identical to its base cannot open a PR.) Commit it using the
   detected commit convention.
4. Push it and open the PR **as a draft**:
   `gh pr create --draft --base <default_branch> --head <dev_branch> --title "<title>" --body "Tracking branch for: <requirements summary>. Design and an implementation plan land first, on a stacked branch, for review before any code does."`
   Record the URL as `state.json`'s `dev_pr_url`.
5. Create the **design branch** from the development branch, locally, and switch to it:
   `git checkout -b <design_branch>` where `design_branch = <dev_branch>-design`. Do not
   push it yet — it has no commits of its own until Phase 2 produces something.
6. Tell the user both branch names and the draft PR URL, then continue directly to
   Phase 2 — this step needs no confirmation.

---

### Phase 2 — Design & Implementation Plan

**Checkpoint**: set `phase=design-plan`. Working branch: `design_branch`.

Spawn a subagent with these instructions:

> Read `.dev-agent/requirements.md` and survey the current repo structure (using the
> source/test layout recorded in `repo_conventions`, plus key config files). Produce
> `.dev-agent/design.md` covering:
> - Modules and classes to create (with file paths)
> - Public method/function signatures and their contracts (inputs, outputs, exceptions)
> - Data flow between components
> - Test strategy: for each component, state whether unit, integration, or e2e tests are appropriate and why
>
> Then produce `.dev-agent/implementation-plan.md` from `design.md` and
> `requirements.md` alone — no test files exist yet, so this is necessarily a general,
> component-by-component plan rather than one derived from concrete test cases:
> - For each file to create or modify: the functions/methods it needs, in the order they
>   should be written, and each one's contract (what it must do, its inputs/outputs,
>   non-obvious detail, and dependencies on other functions).
> - Call out anything the design leaves ambiguous enough that the eventual tests (Phase 4)
>   could reasonably resolve it either way — the plan is guidance for Phase 6, not a
>   contract tests must be bent to fit.
>
> Be concrete in both documents. Every item in the design must map to something testable.

After the subagent completes, summarise both documents and ask:

> "Design and implementation plan complete. Key decisions:
> - {bullet 1}
> - {bullet 2}
> - ...
>
> Push this for review, or would you like to adjust either document first?"

If the user requests adjustments, update the documents accordingly, then ask again.

---

### Phase 3 — Push the design branch, open its PR, and wait

**Checkpoint**: set `phase=awaiting-design-merge`.

1. Commit `.dev-agent/design.md` and `.dev-agent/implementation-plan.md` on
   `design_branch`, using the detected commit convention.
2. Push `design_branch` and open a PR **against `dev_branch`** (not the default branch):
   `gh pr create --base <dev_branch> --head <design_branch> --title "<title>" --body "Design and implementation plan for: <requirements summary>."`
   Record the URL as `state.json`'s `design_pr_url`.
3. Tell the user, explicitly: the PR is open at `{design_pr_url}`, targeting `{dev_branch}`,
   and this skill is now pausing — it will not write a single test or line of
   implementation until that PR is merged.
4. **Stop here.** Do not poll in a loop and do not proceed on your own judgment. When
   the user next runs `/dev-agent --resume` (or otherwise nudges this skill to continue):
   - Check `gh pr view <design_pr_url> --json state,mergedAt`.
   - If it is not merged, say so and stop again — do not re-check repeatedly within the
     same turn.
   - If it **is** merged, still ask: "The design/implementation-plan PR shows merged —
     proceed to writing tests?" Only continue once the user confirms. Merged-but-unconfirmed
     is not a green light by itself; this is the one gate this skill never crosses alone.
5. Once confirmed: check out `dev_branch` and fast-forward it to match the merge —
   `git checkout <dev_branch> && git fetch origin <dev_branch> && git merge --ff-only origin/<dev_branch>`.
   This should always be a clean fast-forward, because `dev_branch` never gained local
   commits of its own beyond the Phase 1 marker; if it is not a clean fast-forward, stop
   and tell the user rather than guessing at a merge.

---

### Phase 4 — Write Tests (TDD)

**Checkpoint**: set `phase=tests`. Working branch: `dev_branch`.

Spawn a subagent with these instructions:

> Read `.dev-agent/design.md`. Write tests for every component described, following
> whatever testing conventions this repo documents (a testing skill under
> `.claude/skills/`, a rule under `.claude/rules/`, `CONTRIBUTING.md`, or `docs/testing.md`
> — see `repo_conventions` for what was found). If the repo has none, use standard TDD
> practice for its language.
>
> Rules:
> - Write tests BEFORE any implementation (TDD).
> - Tests must fail right now because there is no implementation — this is expected and correct.
> - Run the repo's test-collection/dry-run step (e.g. `pytest --collect-only`, `npm test -- --listTests`, the closest equivalent for this test runner) after writing to confirm every test is discovered.
> - A collection failure caused by importing a module Phase 6 has not created yet is the expected TDD red state — leave it. Fix only errors that are the test file's own fault: a syntax error, a wrong import path, a missing fixture/conftest entry, or a reference to something the design does not call for.
> - Do NOT write any implementation code — including a stub module, class, or function created only to satisfy an import.

---

### Phase 5 — Review Loop: Tests

**Checkpoint**: set `phase=review-tests`, `review_iteration=0`.

Run the **review loop** (below) with `target=tests`, reviewing the files added or modified
under the test directory (`git diff --name-only HEAD -- <test_dir>`), and
`max_iterations = state.max_test_iterations`.

After the loop returns, run the repo's aggregate pre-merge check
(`repo_conventions.ci_command`). If the project's CI diffs coverage or lint against a base
branch (check its CI workflow), pass the same base explicitly rather than letting it default
to the wrong branch on a stacked PR — e.g. many repos expose this as a `DIFF_BASE`,
`BASE_REF`, or `--since` flag; use whatever this repo actually supports.

This gate is expected to allow test failures here (tests have no implementation yet) but
must pass on format, lint, and type checks. If it fails on anything other than test
assertions:
- Fix the issues.
- Re-run until it passes.

Create a git commit for the test files only, using this repo's own commit-message
convention (see `repo_conventions`; Conventional Commits' `test:` type is a reasonable
default if the repo uses that style). Record the resulting commit's SHA as
`state.json`'s `test_commit_sha` — Phase 7 needs it to scope its own review. **Do not
push this commit** — `dev_branch` stays local from here on (§Rules).

**Checkpoint**: set `phase=implementation` in `state.json` *before* asking the question
below, not after the user answers it. Tests are already committed at this point, so if the
session ends while waiting here, `--resume` must land in Phase 6, not repeat Phase 5 — a
repeat would find nothing left to review or commit and stall.

Ask the user:

> "Tests committed locally (not pushed). Review ran {N} round(s) and {X} issues were addressed. Proceed to implementation?"

---

### Phase 6 — Implement

**Checkpoint**: set `phase=implementation`.

Spawn a subagent with these instructions:

> Read `.dev-agent/implementation-plan.md` and all test files. Implement the feature step
> by step. The plan was written before the tests existed (§Phase 2) — where a test
> disagrees with the plan on a genuinely ambiguous detail, the test wins; note the
> deviation rather than silently picking one.
>
> Rules:
> - After each logical chunk (one function or one class), run the repo's test runner
>   scoped to the fastest relevant subset (e.g. `pytest -x`, `npm test -- --bail`, or this
>   repo's equivalent) and fix any failures before continuing.
> - Do not proceed to the next chunk while any test is failing.
> - Do not modify test files.

---

### Phase 7 — Review Loop: Implementation

**Checkpoint**: set `phase=review-impl`, `review_iteration=0`.

Run the **review loop** (below) with `target=implementation`, reviewing every file added
or modified since the test commit (`git diff --name-only <state.test_commit_sha> -- .
':!.dev-agent'`), and `max_iterations = state.max_impl_iterations`. Do not restrict this
to the source directory alone — a real feature can also touch a migration, a config file,
or a manifest outside it, and a review scoped only to `<source_dir>` would ship those
unreviewed.

After the loop returns, run the repo's aggregate pre-merge check
(`repo_conventions.ci_command`) one final time. This must be fully green (no failures of
any kind). If it fails, self-fix until green. As in Phase 5, pass an explicit base/diff
reference if this repo's check needs one to compare against the real PR base rather than
defaulting to the wrong branch on a stacked PR.

Create a git commit for the implementation and any test changes, using this repo's commit
convention (Conventional Commits' `feat:` type is a reasonable default if the repo uses
that style). **Do not push this commit** (§Rules).

**Checkpoint**: set `phase=done`.

Print a final summary:
- Phases completed
- Review rounds in each phase and total issues addressed
- Commits created, and that they are local-only
- The still-open draft PR URL (`dev_pr_url`) and a reminder that pushing `dev_branch` and
  marking it ready for review are left to the user
- Any warnings emitted during CI self-fix loops

---

## Rules

- **Local past the design merge.** From Phase 4 onward, nothing on `dev_branch` is
  pushed and no further PR is opened. The draft PR from Phase 1 stays exactly as opened
  (still only the marker commit, or whatever the design merge added to it) until the user
  pushes and un-drafts it themselves.
- **The design/plan merge is the one gate this skill never crosses on its own** (§Phase 3,
  step 4) — not on a timer, not because the API says `mergedAt` is set. Always ask.
- **Branch hygiene.** `dev_branch` never gains local-only commits before the design merge
  (§Phase 3, step 5 relies on this for a clean fast-forward). If something forces one —
  a manual detour, a conflict resolution — say so explicitly rather than silently
  fast-forwarding over lost work.

---

## The review loop (used by Phases 5 and 7)

A bounded loop of automated review → fix, run against either the test files or the
implementation files, tracking issues that survive multiple rounds.

**Reviewer**: if this environment has a code-review MCP tool or subagent available (for
example `mcp__codex-reviewer__*`, or a project-provided review skill such as
`vstorm-code-review`), use it. If none is available, act as the reviewer yourself: read the
target files with a critical, adversarial eye — correctness, missed edge cases, security,
and whether the code actually satisfies `.dev-agent/design.md` / `.dev-agent/requirements.md`
— and produce the same issue list a dedicated reviewer would.

### Workspace

```
.dev-agent/review/{target}/
  round-{N}-issues.json       ← issues found this round
  round-{N}-solutions.json    ← solutions proposed this round
  round-{N}-resolved.json     ← which issue indices were fixed
  unsolved.json               ← cumulative list of issue descriptions never fixed
```

### Loop (repeat while N < max_iterations)

**Step 1 — identify issues.** Ask the reviewer (tool or self-review) to list issues in the
target files, giving it: the files, a one-paragraph summary of `design.md`, the first ~400
characters of `requirements.md`, and the list of previously-unsolved issue descriptions
from `unsolved.json` (empty on round 0). Save the result to
`round-{N}-issues.json`. **If it reports no issues**: clear `unsolved.json` (write `[]`)
— the reviewer just found nothing, so no earlier round's description survives
unconfirmed — then print "Round {N}: no issues found. Stopping loop." and exit the loop.

**Step 2 — propose solutions.** For each issue, build a code snippet (±10 lines around its
location, or the whole file if unclear) and ask for a proposed fix per issue. Save to
`round-{N}-solutions.json`.

**Step 3 — plan, implement, and record resolution.** In severity order (critical → major →
minor): locate the exact spot, apply the fix, and after each fix run the repo's fastest
relevant test check to catch regressions immediately. Do NOT modify files outside the
target set, and do not add features or refactor beyond what the fix requires. Write
`round-{N}-resolved.json` (`resolved` / `unresolved` issue indices, with a reason for each
unresolved one), then rebuild `unsolved.json`: drop descriptions the reviewer no longer
reports, add descriptions of this round's unresolved issues.

**Step 4 — increment and loop.** `N += 1`; update `state.json`'s `review_iteration`; repeat
while `N < max_iterations`.

### After the loop

Print:
```
Review loop complete (target={target}).
Rounds run: {N}
Total issues addressed: {total_resolved}
```

If `unsolved.json` is non-empty, list the unresolved issues and note that they remain in the
code for manual review before shipping.
