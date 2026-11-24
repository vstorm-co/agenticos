# Proof scenario { #proof-scenario }

A change is not done until the agent reproduces the failure, watches it pass,
and can show the evidence. Green mocked tests do not prove that the user
experience works. Proof is evidence observed in the session - command output,
a reproduction, a screenshot - for every change in the diff.

This is Theo's tstack `full-send` "Proof, not diffs" as a capability. The
procedure lives in the `proof-scenario` skill
(`backend/app/core/catalog/skills/proof-scenario/SKILL.md`), which says how
to prove a change; this page says what the capability does with the evidence.

## How a scenario works

The agent records a scenario with `proof_scenario_record` **before fixing
anything**: what it reproduces, how it runs - a command, a reproduction, or a
UI flow - which diff files it exercises, and the before-fix attempt that shows
the failure. After the fix, it runs the **same** reproduction again and
records the after-fix attempt with what it actually saw.

A scenario is proven only when the same reproduction failed before the fix
and passed after it, both times with observed evidence. One half alone proves
nothing: a failure with no passing re-run is a bug report, and a pass with no
failing before-run never showed the fix fixing anything. An attempt that ran
but proved nothing - the command errored before reaching the behaviour, the
screenshot caught the wrong screen - is `inconclusive` and counts as neither
half.

A unit-test run is recorded when the agent hands one over, with evidence kind
`unit_test`, and never counts toward coverage. For UI changes, the evidence is
a screenshot or a watched UI flow - run the app and look - not a component
test.

## The coverage verdict

Before asking for a merge, the agent calls `proof_scenario_verdict` with the
changed files, whether the required checks are green on the current head, how
many are still pending, and how many review findings are still open. The
verdict reports which changed files have observed proof and which do not:

| Verdict | Meaning |
|---|---|
| `proven` | Every changed file is covered by a proven scenario. |
| `partial` | Some files are covered; the report names the rest. |
| `unproven` | No file is covered. |
| `no_scenarios` | Nothing was recorded at all. |

The same call reports the merge gate's proof half: proof, checks, and
findings. All three must hold for the gate to read ready - proof covering the
diff, required checks green with none pending, and no review finding still
open. Ready still merges nothing: merging needs the user's explicit request,
on the current head, with no human review still requesting changes and the
branch up to date and mergeable. Never use `--admin` or any other bypass.

When no way to prove a change can be found, the agent says so and asks the
user, rather than claiming proof it does not have. An unproven change filed
as unproven is honest work; an unproven change filed as proven is not.

## Where the proof lives

Scenarios live on the run manifest, beside the requests and the run reviewer's
corrections, and the run drawer shows each scenario with its attempts and
whether it is proven. There is no migration: scenarios are JSONB on the
manifest, not a table. A run's manifest keeps at most twenty scenarios and
six attempts per scenario, and observed output is clipped before it is kept.

## What it deliberately does not do

- **No merging, no commenting, no action on the change.** Proof and
  reporting only.
- **No proof from unit tests.** A change whose only evidence is a green test
  suite reports as unproven.
- **No invented proof.** What the agent did not see, it did not record.
- **No running anything.** The capability never runs a command itself: the
  agent runs the reproduction and hands over what it observed.
