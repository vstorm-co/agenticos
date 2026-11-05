---
name: platform-automation
description: "Choose and configure AgenticOS routines, watches, event triggers, task reminders and conversation suggestions without duplicating them. Explain schedules, working chats, Inbox cases and notification destinations."
category: automation
---

# One responsibility, one automation

Discover existing routines, watches, agents and connections first. Reuse a matching
responsibility rather than adding another poller. A trigger defines when work
starts; it is not another responsibility to create beside the routine.

| Request | Mechanism | Where the result belongs |
| --- | --- | --- |
| A report every Monday | Scheduled routine, report mode | Configured conversation/primary destination or run log |
| Read an account periodically and report meaningful changes | Watch, a read-only monitoring preset | Findings and working chats, with Inbox attention |
| Check mail hourly and prepare a draft per relevant thread | Routine with `result_mode: inbox`; a watch can also draft read-only text | One private working chat and case per source item |
| Act when a webhook, table event or other supported event arrives | Event routine or workflow entry available in this deployment | Its configured result policy and execution history |
| Remind me once, or let an agent do this once later | Durable Task with Start at | Task board; working chat for agent output; Inbox when attention is needed |
| Suggest better ways to work from past conversations | Conversation suggestions, if enabled | Suggestions for review; no mailbox monitoring or silent activation |
| Follow command output during this reply | `start_monitor` | Current turn only; not a persistent account watch |

## Agree the behavior before enabling it

Use `ask_user_question` for an unresolved cadence, time zone, relevance rule,
audience or external action. Recommend a sensible option and keep the question
short. Do not ask again for details already given or discoverable. In unattended
runs, unavailable/cancelled questions are not consent: leave the blocked decision
for review and keep unrelated work safe.

Read the published agent and its reviewed sources. Verify the exact connection
and capabilities needed; a routine does not gain every new source added to a later
agent version. Changing a title is not a reason to re-review additional access.
Choose either a five-field cron expression in an IANA time zone or one interval,
not both. State the local schedule in words; consider daylight-saving behavior.
Retain default failure protection, existing notification preferences and ordinary
urgency unless the job justifies a change. Never invent supported channels.

Write a complete, self-contained job: sources, scope, relevance rules, time window,
deliverable, stable source item and revision IDs, action limits, and when to stay
quiet. A mailbox draft job says which threads matter, reads the latest thread,
stores the full draft, and does not send it. A watch is read-only even when its
agent can write elsewhere. For event setup, inspect the available trigger schema
or use the corresponding console control if the MCP tool lacks that parameter.

Use a setup proposal card for an unrequested useful automation; it is a reviewable
proposal, not an enabled job. When the person explicitly requests creation, perform
the authorized setup through normal tool approvals. A trial execution is real
work; do not send a test email or mutate production data merely to verify setup.

## Keep the result actionable

Report mode produces the configured report on execution. Inbox mode identifies
source items: unchanged revisions stay quiet and new revisions reuse their case
and working chat. Relevant findings also have durable tasks. Reading a draft or
acknowledging a case means seen, not sent or complete. Resolve only after a
successful requested action or the person's explicit completion. Mute suppresses
that source item. Keep failed or uncertain sends open; check delivery before retry.

Return the routine/watch link, local cadence, reviewed source, active state,
result destination, action limits and any untested integration. Do not promise
email/Slack/phone delivery just because an Inbox case exists.
