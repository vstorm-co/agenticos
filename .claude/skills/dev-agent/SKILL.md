---
name: dev-agent
description: AI development agent. Takes a requirements description and drives the full TDD cycle: design → tests → Codex review → implement → Codex review. Commits tests after Codex review and the full implementation when done.
user-invocable: true
---

# dev-agent

## Usage

```
/dev-agent <requirements text> [--max-test-iterations N] [--max-impl-iterations N]
/dev-agent --resume
```

- `--max-test-iterations N` — Codex review rounds for the test phase (default: 3)
- `--max-impl-iterations N` — Codex review rounds for the implementation phase (default: 3)
- `--resume` — continue from the last checkpoint in `.dev-agent/state.json`

---

## Workspace

All agent state lives in `.dev-agent/` (gitignored). The layout is:

```
.dev-agent/
  requirements.md
  design.md
  implementation-plan.md
  state.json
  codex/
    tests/    round-{N}-issues.json  round-{N}-solutions.json
    impl/     round-{N}-issues.json  round-{N}-solutions.json
```

`state.json` schema:
```json
{
  "phase": "design | tests | codex-tests | plan | implementation | codex-impl | done",
  "codex_iteration": 0,
  "ci_fix_iteration": 0,
  "max_test_iterations": 3,
  "max_impl_iterations": 3,
  "requirements_hash": "<sha256 of requirements.md>",
  "last_checkpoint": "<ISO 8601>"
}
```

---

## Steps

### 0. Initialise or resume

**New run** (`/dev-agent <requirements>`):
1. Parse `--max-test-iterations` and `--max-impl-iterations` from args (default both to 3).
2. Create `.dev-agent/` if it does not exist.
3. Write the requirements text to `.dev-agent/requirements.md`.
4. Compute `sha256` of the file and write `state.json` with `phase=design`, all counters at 0, and the parsed iteration limits.

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

> Read `.dev-agent/requirements.md` and survey the current repo structure (`src/`, `tests/`, key config files). Produce `.dev-agent/design.md` covering:
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

> Read `.dev-agent/design.md`. Write tests for every component described, following the project's testing conventions in `.claude/skills/write-tests/SKILL.md`.
>
> Rules:
> - Write tests BEFORE any implementation (TDD).
> - Tests must fail right now because there is no implementation — this is expected and correct.
> - Run `uv run pytest --collect-only` after writing to confirm all tests are discovered without import errors.
> - If `--collect-only` fails, fix import/syntax errors until it passes.
> - Do NOT write any implementation code.

---

### Phase 3 — Codex Review Loop: Tests

**Checkpoint**: set `phase=codex-tests`, `codex_iteration=0`.

Invoke the `dev-agent-codex-loop` skill, passing the configured limit from `state.json`:

```
/dev-agent-codex-loop --target tests --max-iterations {state.max_test_iterations}
```

After the loop skill returns, run:

```sh
unset VIRTUAL_ENV
DIFF_BASE="origin/$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null || echo main)" make ci
```

On a stacked branch, `DIFF_BASE` must match the PR's real base or the
diff-coverage gate silently diffs against `origin/main` instead — green
locally, red in CI.

The `make ci` gate here allows test failures (tests have no implementation yet) but must pass on format, type checks, and import errors. If `make ci` fails on format or types:
- Fix the issues.
- Re-run `make ci` until it passes.

Create a git commit:

```
git add tests/
git commit -m "test: <feature name> — tests written and Codex-reviewed"
```

Ask the user:

> "Tests committed. Codex ran {N} round(s) and {X} issues were addressed. Proceed to implementation planning?"

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
> - After each logical chunk (one function or one class), run `uv run pytest -x` and fix any failures before continuing.
> - Do not proceed to the next chunk while any test is failing.
> - Do not modify test files.

---

### Phase 6 — Codex Review Loop: Implementation

**Checkpoint**: set `phase=codex-impl`, `codex_iteration=0`.

Invoke the `dev-agent-codex-loop` skill, passing the configured limit from `state.json`:

```
/dev-agent-codex-loop --target implementation --max-iterations {state.max_impl_iterations}
```

After the loop skill returns, run a final:

```sh
unset VIRTUAL_ENV
DIFF_BASE="origin/$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null || echo main)" make ci
```

This must be fully green (no failures of any kind). If it fails, self-fix until green.
On a stacked branch, a bare `make ci` diffs coverage against `origin/main`
instead of the real PR base, so this gate can be green locally while CI's
diff-coverage check is red — `DIFF_BASE` keeps them in sync.

Create a git commit:

```
git add src/ tests/
git commit -m "feat: <feature name> — implementation complete"
```

**Checkpoint**: set `phase=done`.

Print a final summary:
- Phases completed
- Codex rounds in each phase and total issues addressed
- Commits created
- Any warnings emitted during CI self-fix loops
