# Burst { #burst }

One task splits into independent subtasks, runs them in parallel, and merges
the results into one outcome - a burst of parallel work instead of one
sequential run. The agent splits the task first and shows the split to the
person, the way OpenMausBot's `/burst` previews the parts, then one call
fans the parts out to workers side by side and returns the merge.

This is OpenMausBot v0.1.153 Burst mode as a capability: the concept -
preview the split, run the parts in parallel, combine the results -
rebuilt on the fan-out council (#5) and sol-loop (#6) already use. The
procedure lives in the `burst-mode` skill
(`backend/app/core/catalog/skills/burst-mode/SKILL.md`), which says when to
split; this page says what the capability does with the parts.

## How a burst works

The agent calls `run_burst` with the task and the parts, each part a prompt
for its own worker. One call is one burst: the call runs every part in
parallel on the run's own model and merges what comes back, in part order,
under each part's own heading.

After a burst, the agent acts on the failed parts - retry them, do them
directly, or narrow the task - and calls again for a fresh burst. The cap
on bursts is what stops repeated bursts from growing the work: fix what
failed, nothing more. Do not re-run the whole burst to fix one part: burst
the failed parts only.

A burst worker does its own part and nothing else. It does not redo another
part's work and does not widen the task.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `max_subtasks` | `3` | How many subtasks one burst runs at once (2–10) |
| `max_bursts` | `3` | How many bursts one run may ask for (1–5) |

The subtask cap mirrors the subagents `max_fanout` ceiling - default 3,
hard max 10 - rather than raising it. The workers are ambient one-shot
agents on the run's own model, metered against the run's budget; a budget
refusal records the part as failed instead of spending past the cap.

## The merge

Every burst is recorded on the run manifest, and renders as the merged
outcome the burst skill puts in a PR description:

```markdown
## Burst

Task: Write the guide

Parts: 3 - 3 completed, 0 failed.

| B1 | Part 1 | completed |
| B2 | Part 2 | completed |
| B3 | Part 3 | completed |
```

A part that failed reads `failed` with its reason, and the merge names it
under a `FAILED` heading with a footer count - never as a part that
finished, and never dropped from the merge. A burst that lost a part never
reads as one that finished it.

## What it does not do

- **Drop a failed part.** A worker that raises, or returns nothing usable,
  records `failed` with the reason. The merge says so.
- **Invent a result.** The merge is the parts' actual results under their
  own headings. Nothing is summarised away.
- **Raise the fan-out ceiling.** The subtask cap is the subagents ceiling,
  not a new one.
- **Delegate with a spec.** Burst workers are one-shot agents on the run's
  own model, with no spec of their own. A part that needs its own tools,
  credentials, or a standing agent is a delegation through the subagents
  capability, not a burst part.
- **Score the work.** Burst parts do work; they do not judge it. A burst
  that needs judging is a council round after the merge.
- **Fix what failed.** The burst does not fix or iterate on its own. The
  agent retries, does the part directly, or narrows the task, then asks for
  a fresh burst.
- **Keep bursts anywhere but the manifest.** Bursts live in the run
  manifest's JSONB, beside the requests, and read back through the manifest
  schema. There is no table to migrate and no burst to query across runs.
- **Run on a live call.** A burst takes minutes a call cannot wait through,
  so the capability runs in the agent's text twin, handed off from the call.

The capability needs the `agents:delegate` scope, because its workers are
model calls the agent hands work to.
