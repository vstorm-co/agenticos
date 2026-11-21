# Decide what should recur

| Request | Start here | Verify |
| --- | --- | --- |
| Tell me if a supported personal Notion source changes | Monitor and inform | Matching account, source scope, item relevance and delivery |
| Every 30 minutes run my agent to compare Notion and release records | Agent routine in Inbox result mode | Published agent and access, both sources, quiet when nothing changes, stable item identity |
| Every Friday give the decision and three priorities | Agent routine in report mode | Time zone, input sources, audience and actual delivery |
| Transform every incoming supported event into typed rows | Event-triggered workflow | Event schema, mapping, retry and idempotent output |
| Remind me tomorrow to review the release | Private Task | Start time, owner and existing equivalent task |

For a full recurring prompt, state the approved source, comparison window, stable item key, action, destination and when to return no result. Check existing routines and watches for the same job before writing. Confirm what has been saved, what needs one-time review and what can actually run.

## Reports sent to a chat service

Use the connected chat tools to find the bot and authorized destination when working outside the inbound thread. Verify channel ID and whether to reuse a thread or start a new post. Include cadence, time zone, audience and delivery details in the agreed routine prompt. If an action times out, inspect delivery before retrying. Use the console run log for the audit copy. For quick acknowledgements in an active connected chat, use the reaction tool only with a verified message ID.
