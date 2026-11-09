# Agent and team tasks: research and proposal

Status: **proposal only, 2026-11-04**. This change does not create a task
capability, a default TODO table or an automatically maintained team backlog.

## What the references actually provide

OpenBot by nightly-labs separates a chat's execution checklist from ongoing
work: the checklist records steps and is not evidence of completion. A reminder
can bring the bot back later. Delegated work has its own chat and can return a
result to the original conversation. This supports separating a plan from a
persistent responsibility, rather than equating a checked item with a verified
business outcome. Sources: [chat](https://docs.openbot.build/chats/) and
[delegation](https://docs.openbot.build/delegation/).

Its triggers deliver a task message on a schedule or an external event. The
history and returned result are separate from the trigger's settings; access
changes can require renewed confirmation. Source:
[triggers](https://docs.openbot.build/triggers/).

Grok Bot's documented sequence is to complete a task once, capture its method as
a skill, then automate it through a routine. Its setup explicitly reviews the
owner, schedule/time zone, sources, output, approvals and missing-source behavior.
This documentation does not establish a shared, canonical team TODO table.
Source: [skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Proposed AgenticOS model

| Concept | Purpose | Existing platform building block |
| --- | --- | --- |
| Plan | Steps within the current run | Planning capability and chat checklist |
| Task | A responsibility with an owner and a verifiable result | A proposed Virtual Tables preset |
| Routine | When to revisit a responsibility or produce a report | Existing routines and their run history |
| Watch | Detect relevant changes in an approved source | Existing personal watches and Inbox |
| Memory | Durable facts, preferences and decisions | Existing claims and notes; never the authoritative task queue |

Use one optional project/team task table, shared through existing project and
table permissions. Start with `title`, `status`, `assignee`, `due_at`,
`next_check_at`, `blocked_reason`, `expected_result`, and `evidence`. Keep links to
the conversation, originating record, routine/watch, agent and run. An agent can
be the executor while a human remains accountable. Do not provision a separate
table for every agent or duplicate records already owned by Linear or another
connected tracker.

Suggested states: `todo`, `in_progress`, `blocked`, `needs_review`, `done`,
`cancelled`. Completion needs evidence appropriate to the task: an artifact,
a confirmed provider result, or a person's review. A model saying "done" is not
sufficient. Repeating a run must update the same task id, not create duplicates.
External actions retain existing approval and source-consent checks.

## User experience to validate before implementation

The agent first proposes a task card with a title, owner, expected outcome and
next check. Accepting it writes the reviewed task through AgenticOS MCP. Chat
shows status, blockers and the latest linked result; the project can offer a list
and board over the same records. A team backlog is visible only to its members,
while private agent work stays private. A routine can check due tasks and a watch
can propose a status change; neither silently marks a task complete.

Reuse the existing project tracking preset where it fits. Before implementation,
settle whether assignees may be users, agents or both, who accepts completion,
how external trackers remain authoritative, and how recurring work reopens or
creates task occurrences. No new table or UI is shipped by this proposal.
