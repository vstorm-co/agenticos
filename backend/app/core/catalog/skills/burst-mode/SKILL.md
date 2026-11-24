---
name: burst-mode
description: Trigger this if the user says 'burst'.
category: engineering
---

# Burst mode

Split one task into independent subtasks, run them in parallel, and merge
the results into one outcome - a burst of parallel work instead of one
sequential run. This is OpenMausBot's Burst mode as a T3OS procedure: the
bot previews the parts, runs them side by side, and gives you one result.

Use it when one task genuinely splits into parts that do not depend on
each other: research in several directions at once, drafts of separate
sections, checks over separate files. Do not burst a task that is really
one sequential job - if part two needs part one's answer, it is not a
burst, it is a sequence.

## 1. Split, and preview the split

Break the task into 2 to 3 parts by default, at most 10. Each part needs
everything its worker needs in its own prompt: what to do, what it may
read, and what its result should look like. Parts must be independent: no
part reads another part's result, and no two parts edit the same file.

Show the split to the person before running it, and let them correct it.
A burst the person did not see coming is a burst they cannot steer.

## 2. Run the burst

In T3OS, run the burst through the burst capability's `run_burst` tool:
one call is one burst, with the task and the parts. The call fans the
parts out to workers in parallel and returns the merged outcome. Elsewhere,
use the harness's subagent tools.

Do not edit files a worker is working on while the burst runs. Do not
start a second burst over the same parts. A worker that is slow is not a
worker that failed - wait for the burst to return.

## 3. Read the merge, and act on what failed

The merge lists each part under its own heading, with a footer counting
completed against attempted. A part that failed reads `failed` with its
reason - never as a part that finished, and never dropped from the merge.

For each failed part, in order:

- Retry it as a fresh burst, with a narrower prompt, when the failure was
  the worker's - a timeout, an empty result, a misunderstanding.
- Do it directly yourself, when the part needs judgement or access a
  worker does not have.
- Narrow the task and drop the part, when the part turns out not to be
  needed - and say so, rather than leaving the merge silent about it.

Do not present the merge as complete while a part is failed. Do not
re-run the whole burst to fix one part: burst the failed parts only.

## 4. Stop

A burst is done when every part completed, or when every failed part has
been retried, done directly, or deliberately dropped with a reason. At
most 3 bursts per run by default, 5 at most: repeated bursts are for
failed parts, not for widening the task. If the work ends in a pull
request, put the results in the PR description. Put this section before
the model and harness line at the end:

```markdown
## Burst

Task: <the task>

Parts: 3 - 3 completed, 0 failed.

| B1 | Part 1 | completed |
| B2 | Part 2 | completed |
| B3 | Part 3 | completed |
```

If a part failed, write `failed (<reason>)` in its row. Do not invent a
result for it. If the PR is open, edit the description. Do not post a
comment for this. If there is no PR, put the same results in the final
reply only.

## What burst is not

- **Not a council.** Burst parts do work; they do not score it. A burst
  that needs judging is a council round after the merge, not a burst with
  scores on it.
- **Not a sol-loop.** The burst does not fix what it finds or iterate on
  its own. The agent retries, fixes, or narrows - then asks for a fresh
  burst.
- **Not delegation.** Burst workers are one-shot agents on the run's own
  model, with no spec of their own. A part that needs its own tools,
  credentials, or a standing agent is a delegation through the subagents
  capability, not a burst part.
