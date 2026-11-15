# Burst

Split one task into independent subtasks, run them in parallel, and merge
the results into one outcome - a burst of parallel work instead of one
sequential run. The calling agent splits the task first and shows the split
to the person, the way OpenMausBot's `/burst` previews the parts, then one
call fans the parts out to workers side by side and returns the merge.

This is OpenMausBot v0.1.153 Burst mode as a capability, not a copy of its
code: the concept - preview the split, run the parts in parallel, combine
the results - rebuilt on the fan-out council (#5) and sol-loop (#6) already
use. The skill file at
`backend/app/core/catalog/skills/burst-mode/SKILL.md` is the procedure; this
capability is how an agent runs it.

## Why a capability, and why one tool

A burst is a decision the agent makes mid-run - "does this split?" - so it
is a tool the model calls, not instructions baked in at build time. One
tool, `run_burst`, because one call is one burst: the agent splits, bursts,
then acts on the failed parts and calls it again for a fresh burst, and the
burst number on the manifest is what makes "ran twice" a checkable fact
rather than a feeling.

## What it deliberately does not do

- **No silent failures.** A worker that raises, or returns nothing usable,
  records `failed` with the reason, and the merge names it under a `FAILED`
  heading with a footer count. A burst that lost a part never reads as one
  that finished it.
- **No invented results.** The merge is the parts' actual results under
  their own headings. Nothing is summarised away, and a failed part's
  heading carries no result it did not produce.
- **No raised ceiling.** The subtask cap mirrors the subagents `max_fanout`
  ceiling - default 3, hard max 10 - rather than raising it. A burst shares
  the run's budget through the ambient calls, and a budget refusal records
  the part as failed instead of spending past the cap.
- **No spec'd delegates.** The workers are ambient one-shot agents on the
  run's own model, the same fan-out council and sol-loop use. A part that
  needs its own spec, tools, or credentials is a delegation through the
  subagents capability, not a burst part.
- **No council scoring.** Burst parts are not reviewers and give no scores;
  a burst that needs judging is a council round after the merge, not a
  burst with scores on it.
- **No sol-loop.** The burst does not fix what failed or iterate on its own.
  The agent retries, does the part directly, or narrows the task, then
  asks for a fresh burst.
- **No migration.** Bursts live in the run manifest's JSONB, beside the
  requests and the run reviewer's corrections, and read back through the
  manifest schema. There is no table to migrate and no burst to query
  across runs.

## Voice

A burst runs in the agent's text twin, not on a realtime call: a burst
takes minutes a call cannot wait through, and its workers are ambient model
calls. `voice="hand_off"`.
