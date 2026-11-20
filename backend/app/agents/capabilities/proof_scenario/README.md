# Proof scenario

A change is not done until the agent reproduces the failure, watches it pass,
and can show the evidence. Green mocked tests do not prove that the user
experience works.

A **proof scenario** names one reproduction for a change - a command to run, a
reproduction to watch, a UI flow to look at - and which files of the diff it
exercises. A **proof attempt** is one observed run of that scenario, before
the fix or after it, with what was actually seen: command output, the
reproduction's result, a screenshot's description. A scenario is proven only
when the same reproduction failed before the fix and passed after it, both
times with observed evidence. The coverage verdict reports which changed
files have that proof and which do not, and the merge gate's proof half adds
the required checks and the open review findings.

This is Theo's tstack `full-send` "Proof, not diffs" as a capability, not a
new merge process invented here. The skill file at
`backend/app/core/catalog/skills/proof-scenario/SKILL.md` is the procedure;
this capability is how an agent runs it.

## Why a capability, and why two tools

Proving a change is a decision the agent makes mid-run - "have I actually
seen this work?" - so it is tools the model calls, not instructions baked in
at build time. Two tools: `proof_scenario_record`, one call per observed
attempt, and `proof_scenario_verdict`, which reads the manifest and reports
the coverage verdict over the diff. One call is one attempt: the agent runs
the reproduction, hands over what it saw, and the verdict is computed from
what the run recorded rather than remembered.

## What it deliberately does not do

- **No merging, no commenting, no action on the change.** Proof and
  reporting only. The verdict is a report the agent reads before it asks a
  human to merge; a ready gate still merges nothing.
- **No proof from unit tests.** A unit-test run is recorded when the agent
  hands one over, with evidence kind `unit_test`, and never counts toward
  coverage. A change whose only evidence is a green test suite reports as
  unproven.
- **No invented proof.** A scenario with only a failing before-run is a bug
  report; a scenario with only a passing after-run never showed the fix
  fixing anything. Both halves are required, and an inconclusive attempt
  counts as neither. When no way to prove a change can be found, the agent
  says so and asks the user.
- **No running anything.** The capability never runs a command itself: the
  agent runs the reproduction - in the sandbox, in a test run, in the
  console - and hands over what it observed. The observed output is
  clipped before it is kept, so a manifest cannot outgrow its ceiling on
  one verbose command.
- **No migration.** Scenarios live in the run manifest's JSONB, beside the
  requests and the run reviewer's corrections. There is no table to migrate
  and no scenario to query across runs.

## Voice

Proving a change takes minutes the call cannot wait through: reproductions
run, fixes land, the same reproduction runs again. `voice="hand_off"`.
