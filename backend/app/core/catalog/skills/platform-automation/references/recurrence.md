# Decide what should recur

| Request | Start here | Verify |
| --- | --- | --- |
| Tell me if a supported personal Notion source changes | Monitor and inform | Matching account, source scope, item relevance and delivery |
| Every 30 minutes run my agent to compare Notion and release records | Agent routine in Inbox result mode | Published agent and access, both sources, quiet when nothing changes, stable item identity |
| Every Friday give the decision and three priorities | Agent routine in report mode | Time zone, input sources, audience and actual delivery |
| Transform every incoming supported event into typed rows | Event-triggered workflow | Event schema, mapping, retry and idempotent output |
| Remind me tomorrow to review the release | Private Task | Start time, owner and existing equivalent task |

For a full recurring prompt, state the approved source, comparison window, stable item key, action, destination and when to return no result. Check existing routines and watches for the same job before writing. Confirm what has been saved, what needs one-time review and what can actually run.

## Schedule from the person’s context

Use a weekday already stated in this conversation or recorded in the selected Inbox evidence as the first suggested option. Label an evidence-based suggestion as a suggestion until the person confirms it. Ask only for missing details such as the hour, time zone or destination; do not replace an observed Thursday with an unrelated menu of weekdays. The saved schedule must reflect the person’s answer, including a free-text alternative.

## Routine access

New routines automatically admit the selected published agent’s initial available configuration within the creator’s current permissions. No separate setup or action review is required by default. Later additions of sources, accounts or tools, or changes to instructions, variables, effective skills, context or delegated behavior require the owner’s access review; another publisher cannot extend that authority by publishing alone. Safe source removals and changes limited to the root agent’s model or display metadata can follow without a new review. Changing a pinned delegate version requires review. An optional MCP service without an available account is left unavailable, as in ordinary chat; a web-only task does not require connecting an unused GitHub account. The agent’s own approval rules, mandatory platform approvals and native folder consent still apply. A required event-input account or missing creator identity remains a real blocker.

The owner can optionally choose a reviewed source snapshot in the routine’s access settings. Existing reviewed routines keep their restrictions until the owner explicitly changes the mode. Each new following run stays inside the approved ceiling and snapshots its available sources; a waiting or resumed run cannot borrow a replacement account or unreviewed instruction content. A legacy following policy without behavior proof requires owner review; existing restricted policies retain their rules. If a receipt says `setup_required=true`, describe it as saved but paused, name the observed blocker and link `/routines`. Repair or explicitly change that existing routine. Do not promise unattended delivery, create duplicates or remove a binding from a shared agent as though that only changed this routine.

## Reports sent to a chat service

Use the connected chat tools to find the bot and authorized destination when working outside the inbound thread. Verify channel ID and whether to reuse a thread or start a new post. Include cadence, time zone, audience and delivery details in the agreed routine prompt. If an action times out, inspect delivery before retrying. Use the console run log for the audit copy. For quick acknowledgements in an active connected chat, use the reaction tool only with a verified message ID.
