---
name: durable-work
description: "Carry a large job through planning, specialists, coding tools, background topics and durable Tasks without losing decisions or claiming unfinished work is done. Use for long implementation, multi-stage research and work continued across chats."
category: operations
---

# Keep the goal, evidence and next action explicit

Read the request, relevant project instructions, current resources and previous
decisions before changing anything. State an observable deliverable and a short
plan for substantial work. Continue authorized work through implementation and
verification; a plan or a dispatched subagent is not the requested outcome.
Keep progress updates brief: result, uncertainty and the next useful check.

## Choose the lifetime of the work

| Lifetime | Mechanism | Completion requirement |
| --- | --- | --- |
| Steps inside this run | Brief progress messages | Update after evidence, not after dispatch |
| Independent investigation inside this run | Subagent task/delegate | Collect and check its returned evidence |
| Slow tool while other steps proceed | Its supported `run_in_background` option | Consume the result before depending on it |
| Command output during this turn | `start_monitor` | Stop when finished; not available in every shell |
| Separate conversation continuing while the person chats | `start_background_task` | Use the returned topic/status; avoid duplicates |
| Commitment surviving runs or scheduled once | Managed Task | Persist owner, Next step, Start at and working-chat link |
| Recurring responsibility | Routine or watch | Agreed sources, cadence, result policy and active state |

Background tool calls and transient specialists do not become durable work merely
because they are asynchronous. Do not promise completion after this run unless a
topic, task or routine was actually created. Use the links and status returned by
the tool. Respect shared budget, fan-out and approval limits; asynchronous work
does not widen authority. Do not poll a monitor that already pushes output.

## Delegate bounded work

Use `research` for primary sources, `explore` for workspace evidence and `review`
for defects in a concrete artifact. Independent briefs can run together. State
the question, known facts, allowed actions, relevant files, output shape and
completion criteria. A specialist is not guaranteed to see this whole chat.
Dynamic specialists have no tools or private knowledge by default. A persistent
platform agent is created with platform `create_agent_draft`; transient
`create_agent`/`delegate` is not that operation.

Use the listed Architect delegate for AgenticOS setup when offered. Other agents
are available only through the current delegation catalog and live permissions.
Avoid circular delegation and overlapping writes. Keep integration and final
verification with the lead agent; a subagent's confidence is not evidence.

For coding, use `run_coding_agent` only when configured. Provide the repository,
goal, constraints, permitted files, acceptance tests and current state. Read back
its changes and tests. A local Claude Code/Codex harness uses the paired desktop
and approved folder; a sandbox harness needs configured credentials. Do not copy
tokens between accounts, invent a local run from web chat, or assume a skill
installs either CLI. Commit/push only when authorized by the person's request.

## Recover and finish

Keep durable project decisions in project material, private preferences in Memory
and pending actions in Tasks. Before a handoff or continuation, save a concise
state: completed deliverables and links, actual test results, remaining blockers,
next action and its owner. Do not dump the whole transcript into Context.

When blocked on a real choice, use `ask_user_question` with useful options. Read
discoverable facts yourself, avoid repeated questions, and continue independent
authorized work. A cancelled or unavailable question is not approval. Finish with
the result, links, verification and material limits. Never claim “sent”, “live”,
“tested” or “done” from an unexecuted plan, queued run or unsupported tool.
