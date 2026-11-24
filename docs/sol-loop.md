# Sol-loop { #sol-loop }

One reviewer judges the work before it goes out, in rounds, until it passes
or the budget ends. Round 1 reviews the whole change; later rounds check
only the changed code and the open findings. The agent fixes what the
reviewer found and calls again for a fresh round.

This is the sol-loop skill as a capability. The procedure lives in the
`sol-loop` skill (`backend/app/core/catalog/skills/sol-loop/SKILL.md`),
which says when to ask for a review; this page says what the capability does
with the answer.

## How a round works

The agent calls `run_sol_loop_review` with the work and the context it needs.
One call is one round: the call asks the one configured reviewer for a
verdict and findings with stable ids.

After a round, the agent fixes what the reviewer found and calls it again
for a fresh round, until the verdict is APPROVE on the current diff. The cap
on rounds is what stops repeated reviews from growing the work: fix what was
asked, nothing more. A round whose findings are all nits stops early - there
is no new round for declined nits.

A reviewer's review is read-only. It judges the work as it stands; it does
not edit it, commit, comment, or start subagents or reviewers.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `reviewer` | — | The one reviewer: a name, a provider, and a model profile |
| `max_rounds` | `3` | How many review rounds one run may ask for (1–5) |

The reviewer reviews on its profile's **primary** model only. A profile's
fallback chain is never used here: a fallback would silently substitute
another model when the first is down, and a review by a substitute is not
the review the operator configured. The code does not enforce that the model
is a Sol model: the operator points the reviewer profile at their Sol model,
and naming a version in code would go stale the moment a newer Sol ships.

## The ledger

Every round is recorded on the run manifest, and renders as the findings
ledger the sol-loop skill keeps:

```markdown
## Sol-loop review

Rounds: 2

| Round | Scope | Verdict | Stop |
| --- | --- | --- | --- |
| 1 | full | CHANGES | — |
| 2 | changed-only | APPROVE | approved |

| Finding | Severity | File | Outcome |
| --- | --- | --- | --- |
| S1 | blocker | app/x.py | agree-fixed |
```

A finding nobody has answered yet reads `open`. A reviewer that could not be
reached reads `unavailable`, with the reason - never a verdict it did not
give, and never approval. Budget end reads `budget_exhausted`, and is not
approval either. A finding disputed after two replies reads `stuck`: the user
decides. Review usage reads `not exposed`: the review call returns only the
review, never its token use.

## What it does not do

- **Fix what it finds.** Sol-loop judges; the agent fixes, then asks for a
  fresh round.
- **Keep rounds anywhere but the manifest.** Rounds live in the run
  manifest's JSONB, beside the requests. There is no table to migrate and no
  round to query across runs.
- **Substitute a reviewer.** A reviewer whose model did not resolve is
  reported unavailable, never replaced by another model.
- **Guess usage.** The ledger says usage is not exposed rather than
  inventing a number.
- **Run on a live call.** A review takes minutes a call cannot wait through,
  so the capability runs in the agent's text twin, handed off from the call.

The capability needs the `agents:delegate` scope, because its reviewer is a
model call the agent hands work to.
