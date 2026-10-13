# Planning

A checklist the agent keeps for itself while it works: `write_plan` to lay it out,
`read_plan` to see the step ids, and granular tools to move steps between statuses.
Under `enable_subtasks` it also gets dependency-aware planning — `add_subtask`,
`set_dependency`, `get_available_tasks`, and a `blocked` status a step sits in until
its prerequisites resolve.

The tools, the plan store and the cache-safe reminder come from
`pydantic_ai_harness.planning`. This package registers that capability into the
platform, declares the tool text and owns the two integration decisions the library
leaves to its caller.

## Why the plan is a reminder, not the system prompt

For multi-step work a model does better when it writes the steps down first and keeps
them in front of itself. So the current plan is surfaced back every turn — but as an
*ephemeral tail reminder* appended after a cache breakpoint, never in the system
prompt. The stable prompt prefix stays byte-identical across turns, so a provider's
prompt cache is not invalidated by a plan that changes every step; only the mutable
reminder is re-read. `cache_ttl` is how long that prefix may cache.

## Why the store is the runner's

The library's default `InMemoryPlanStore` is fresh per run, and a run here is one
turn. That costs the checklist at two boundaries. A run that parks on an approval
mid-plan resumes as a *new* pydantic-ai run, so a fresh store would drop what the
model had built — the same shape of bug the delegation journal had before
agenticos#175. And a chat message is a run, so the next message would drop it too:
an agent wrote three steps, was asked to start the first, and answered that no plan
existed and it had never created one (agenticos#1077).

So the runner owns the store, not this capability. It seeds one from the
conversation's `plan_items` — or from `paused_state` on a resume, which is the newer
copy — injects it through `PLANNING_STORE_RESOURCE`, and writes the checklist back
to the conversation when the run stops. The capability only hands that store to the
library — which is why building it needs no runner change, exactly as the subagent
runtime arrives as a resource. Absent a runner (a preview, a unit test), the library
keeps its own fresh in-memory plan, which is the honest behaviour for a build with
no run to park.

A finished checklist is kept rather than cleared: that is what the run which
finished it saw too — every step ticked in the tail reminder until `write_plan`
replaces the plan wholesale, which is what starting new work does.

## Why the tool text lives here

A tool's description is the strongest prompt in the product — the model reads it
before deciding to call the tool. The nine descriptions are declared in
`_capability.py` and handed to the library through `descriptions=`, so the text the
model reads, the text the Builder shows an operator choosing what needs approval, and
the text this repository's tests assert on are one string. It is the same bargain
`sandbox` strikes with its console library.

## Relationship to Delegation (`subagents`)

Planning decides *what* the steps are; delegation decides *who* does them. They are
orthogonal — a plan is a toolset plus a reminder, delegation is a toolset plus a run
wrapper, and neither restructures the other — so an agent may bind both, one, or
neither.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `enable_subtasks` | `false` | Adds the three subtask/dependency tools and the `blocked` status. |
| `cache_ttl` | `5m` | How long the prompt prefix before the plan reminder may cache: `5m` or `1h`. |

## What this deliberately does not do

**It spends no tokens of its own.** The tools are local checklist edits with no model
or embedding request behind them, so there is no ambient usage to meter — unlike
knowledge (embeddings) or delegation (child runs). The round trips the model makes to
call them are its own, already counted by the budget guard.

**It exposes no persistent backend.** The library ships SQLite, Postgres and Redis
stores, each of which owns its own queries; this capability uses the in-memory one
and the runner makes it durable, writing the checklist to `conversations.plan_items`
through the repository layer like every other row this application keeps. A second
writer of the same plan is what a library store would be.
