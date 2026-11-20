# Sol-loop

One reviewer judges the work, in rounds, until it passes or the budget ends.
Round 1 reviews the whole change; later rounds check only the changed code
and the open findings. The agent fixes what the reviewer found and calls
again for a fresh round. Each round's verdict and findings land on the run
manifest as a ledger, which the run drawer shows.

This is Theo's tstack sol-loop skill as a capability, not a new review
process invented here. The skill file at
`backend/app/core/catalog/skills/sol-loop/SKILL.md` is the procedure; this
capability is how an agent runs it.

## Why a capability, and why one tool

A review round is a decision the agent makes mid-run - "is this ready?" - so
it is a tool the model calls, not instructions baked in at build time. One
tool, `run_sol_loop_review`, because one call is one round: the agent fixes
what the reviewer found and calls it again, and the round number on the
manifest is what makes "reviewed twice" a checkable fact rather than a
feeling.

## What it deliberately does not do

- **No substitution.** A reviewer whose model did not resolve, or whose
  review fails, is reported `unavailable` with the reason. Swapping in
  another model would review with a reviewer the operator did not choose,
  and a round that quietly became a review by nobody would read as a review.
- **No invented verdicts.** A reviewer that gives no verdict records
  `no_verdict`. Budget end is not approval: a loop that runs out of rounds
  with a blocker or should still open stops as `budget_exhausted`, and is not
  satisfied.
- **No scope creep.** The cap on rounds (`max_rounds`, default 3, at most 5)
  is what stops repeated reviews from growing the work. The reviewer judges
  the work as it stands; it does not propose work outside its scope. A round
  whose findings are all nits stops early as `nits_only`.
- **No fixing.** Sol-loop judges; the agent fixes, then asks for a fresh
  round. The capability never edits, commits, or comments.
- **No sub-reviewers.** One reviewer only. The reviewer must not start
  subagents or reviewers.
- **No guessed usage.** The review call returns only the review, never its
  token use, so the ledger says usage is not exposed rather than guessing it.
- **No migration.** Rounds live in the run manifest's JSONB, beside the
  requests and the run reviewer's corrections. There is no table to migrate
  and no round to query across runs.

## Models

The reviewer reviews on its profile's **primary** model only. A profile's
fallback chain is never used here: a fallback would silently substitute
another model when the first is down, and a review by a substitute is not
the review the operator configured. The runner resolves the profile and the
factory hands the resolved model to the builder; the capability never
touches the vault.

The code does not enforce that the model is a Sol model: the operator points
the reviewer profile at their Sol model, and naming a version in code would
go stale the moment a newer Sol ships. A reviewer pointed anywhere else
still reviews - it is the operator's choice, not the code's.

## Voice

A sol-loop review runs in the agent's text twin, not on a realtime call: a
review takes minutes a call cannot wait through, and its reviewer is an
ambient model call. `voice="hand_off"`.
