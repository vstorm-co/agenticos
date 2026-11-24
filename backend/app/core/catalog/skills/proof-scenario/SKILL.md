---
name: proof-scenario
description: Use when proving a change with observed evidence before merging it.
category: engineering
---

# Proof scenario

A change is not done until you reproduce the failure, watch it pass, and can
show the evidence. Green mocked tests do not prove that the user experience
works. Proof is evidence observed in the session - command output, a
reproduction, a screenshot - for every change in the diff.

## 1. Record the reproduction before the fix

Run `git status --short` and `git diff --stat` against the merge base. The
changed files are the diff the proof must cover.

For each behaviour the change touches, record a scenario with
`proof_scenario_record` **before fixing anything**:

- `scenario_id` - a stable id, e.g. `P1`.
- `name` - what it reproduces, in one line.
- `kind` - `command`, `reproduction`, or `ui`.
- `command` - what to run or watch, so the reproduction can be repeated.
- `covers` - the diff files this scenario exercises.
- `phase` - `before_fix`.
- `status` - `failed` when the reproduction shows the failure.
- `evidence_kind` - `command_output`, `reproduction`, `screenshot`, or
  `ui_observation`.
- `observed` - what was actually seen. Paste the failing output, not a
  summary of it.

A scenario with no failing before-run never showed the fix fixing anything.
If the failure cannot be reproduced, say so now: the change has no proof yet,
and the next step is finding a reproduction, not writing the fix.

## 2. Fix, then watch the same reproduction pass

Apply the fix - minimal, scoped to the change. Then run the **same**
reproduction again and record the after-fix attempt with
`proof_scenario_record`, same `scenario_id`, `phase` `after_fix`, `status`
`passed`, and what you actually saw.

A scenario is proven only when the same reproduction failed before the fix
and passed after it, both times with observed evidence. An attempt that ran
but proved nothing - the command errored before reaching the behaviour, the
screenshot caught the wrong screen - is `inconclusive` and counts as
neither half.

A green unit test is not proof. Record it if you ran one, with evidence kind
`unit_test`: it is kept on the manifest and never counts toward coverage.
Do not present a passing test suite as proof that the user experience works.

For UI changes, run the app and look: a screenshot or a watched UI flow is
the evidence, not a component test.

## 3. Ask for the verdict before asking for a merge

Call `proof_scenario_verdict` with the changed files, whether the required
checks are green on the current head, how many are still pending, and how
many review findings are still open. It reports the coverage verdict:

- `proven` - every changed file is covered by a proven scenario.
- `partial` - some files are covered; the report names the rest.
- `unproven` - no file is covered.
- `no_scenarios` - nothing was recorded at all.

It also reports the merge gate's proof half: proof, checks, and findings.
All three must hold for the gate to read ready - and ready still merges
nothing. Merging needs the user's explicit request, on the current head,
with no human review still requesting changes and the branch up to date and
mergeable. Never use `--admin` or any other bypass.

## 4. When you cannot prove a change

When you cannot find a way to prove a change, you do not have full
confidence. Do not claim proof you do not have, and do not dress up a test
run as observed evidence. Say what you tried, what is still unproven, and
ask the user - they may know a reproduction you do not, or may accept the
change unproven with eyes open. An unproven change filed as unproven is
honest work; an unproven change filed as proven is not.

## What this skill never does

- Never merges, approves, comments, or takes any action on the change.
  Proof and reporting only.
- Never substitutes a different reproduction after the fix: the after-fix
  attempt must be the same scenario that failed before it.
- Never invents observed output. What you did not see, you did not record.
