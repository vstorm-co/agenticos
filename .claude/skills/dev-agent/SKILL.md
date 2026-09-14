---
name: dev-agent
description: AI development agent. Takes a requirements description and drives the full TDD cycle: design → tests → review → implement → review. Commits tests after review and the full implementation when done. Portable across repos — detects the project's own test runner, source/test layout, and CI command rather than assuming one.
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

---

## Before the first phase — learn the repo

This skill runs in any repo, so nothing below is hardcoded. Before Phase 1, determine
and record (in `.dev-agent/state.json` under `repo_conventions`):

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
  "phase": "design | tests | review-tests | plan | implementation | review-impl | done",
  "review_iteration": 0,
  "ci_fix_iteration": 0,
  "max_test_iterations": 3,
  "max_impl_iterations": 3,
  "requirements_hash": "<sha256 of requirements.md>",
  "last_checkpoint": "<ISO 8601>",
  "repo_conventions": {
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
2. Create `.dev-agent/` if it does not exist.
3. Write the requirements text to `.dev-agent/requirements.md`.
4. Run the repo-discovery pass above and record `repo_conventions`.
5. Compute `sha256` of the requirements file and write `state.json` with `phase=design`,
   all counters at 0, the parsed iteration limits, and `repo_conventions`.

**Resume** (`/dev-agent --resume`):
1. Read `.dev-agent/state.json`.
2. If it does not exist, tell the user there is nothing to resume.
3. If `requirements_hash` has changed since the checkpoint, warn the user: "Requirements changed since last checkpoint — continuing anyway. Use `/dev-agent <requirements>` to restart from scratch."
4. Ask: "Resume from phase **{phase}** (checkpoint: {last_checkpoint})? Or restart from scratch?" If the user chooses restart, delete `.dev-agent/` and re-run as a new run.
5. Jump to the step matching `state.json.phase`.

---

### Phase 1 — Design

**Checkpoint**: set `phase=design` in `state.json`.

Spawn a subagent with these instructions:

> Read `.dev-agent/requirements.md` and survey the current repo structure (using the
> source/test layout recorded in `repo_conventions`, plus key config files). Produce
> `.dev-agent/design.md` covering:
> - Modules and classes to create (with file paths)
> - Public method/function signatures and their contracts (inputs, outputs, exceptions)
> - Data flow between components
> - Test strategy: for each component, state whether unit, integration, or e2e tests are appropriate and why
>
> Be concrete. Every item in the design must map to something testable.

After the subagent completes, summarise the design in 3–5 bullet points and ask:

> "Design complete. Key decisions:
> - {bullet 1}
> - {bullet 2}
> - ...
>
> Proceed to writing tests, or would you like to adjust the design first?"

If the user requests adjustments, update `.dev-agent/design.md` accordingly, then ask again.

---

### Phase 2 — Write Tests (TDD)

**Checkpoint**: set `phase=tests`.

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
> - Run the repo's test-collection/dry-run step (e.g. `pytest --collect-only`, `npm test -- --listTests`, the closest equivalent for this test runner) after writing to confirm all tests are discovered without import/syntax errors.
> - If that check fails, fix import/syntax errors until it passes.
> - Do NOT write any implementation code.

---

### Phase 3 — Review Loop: Tests

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
default if the repo uses that style).

Ask the user:

> "Tests committed. Review ran {N} round(s) and {X} issues were addressed. Proceed to implementation planning?"

---

### Phase 4 — Implementation Planning

**Checkpoint**: set `phase=plan`.

Spawn a subagent with these instructions:

> Read `.dev-agent/design.md` and all test files. Produce `.dev-agent/implementation-plan.md`.
>
> The plan must be file-by-file and function-by-function:
> - For each file to create or modify: list the exact functions/methods to implement, in the order they should be written.
> - For each function: state its contract (what it must do to make the tests pass), any non-obvious implementation detail, and dependencies on other functions.
>
> The plan is done when following it step-by-step would make all tests pass.

After the subagent completes, summarise the plan and ask:

> "Implementation plan ready.
> - Files to create/modify: {list}
> - Estimated steps: {N}
>
> Proceed with implementation?"

---

### Phase 5 — Implement

**Checkpoint**: set `phase=implementation`.

Spawn a subagent with these instructions:

> Read `.dev-agent/implementation-plan.md` and all test files. Implement the feature step by step.
>
> Rules:
> - After each logical chunk (one function or one class), run the repo's test runner
>   scoped to the fastest relevant subset (e.g. `pytest -x`, `npm test -- --bail`, or this
>   repo's equivalent) and fix any failures before continuing.
> - Do not proceed to the next chunk while any test is failing.
> - Do not modify test files.

---

### Phase 6 — Review Loop: Implementation

**Checkpoint**: set `phase=review-impl`, `review_iteration=0`.

Run the **review loop** (below) with `target=implementation`, reviewing the files added or
modified under the source directory (`git diff --name-only HEAD -- <source_dir>`), and
`max_iterations = state.max_impl_iterations`.

After the loop returns, run the repo's aggregate pre-merge check
(`repo_conventions.ci_command`) one final time. This must be fully green (no failures of
any kind). If it fails, self-fix until green. As in Phase 3, pass an explicit base/diff
reference if this repo's check needs one to compare against the real PR base rather than
defaulting to the wrong branch on a stacked PR.

Create a git commit for the implementation and any test changes, using this repo's commit
convention (Conventional Commits' `feat:` type is a reasonable default if the repo uses
that style).

**Checkpoint**: set `phase=done`.

Print a final summary:
- Phases completed
- Review rounds in each phase and total issues addressed
- Commits created
- Any warnings emitted during CI self-fix loops

---

## The review loop (used by Phases 3 and 6)

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
`round-{N}-issues.json`. **If it reports no issues**, print "Round {N}: no issues found.
Stopping loop." and exit the loop.

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
