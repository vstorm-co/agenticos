# Routines, watches and tasks

Unattended work on an agent. Tools are written `agenticos:<tool>`; match on the tool name whatever the server is called. Deterministic multi-step pipelines are workflows, covered in the workflows reference that SKILL.md lists.

## Contents

- Which one
- Routines
- Watches
- Tasks
- Organization settings

## Which one

| Intent | Mechanism |
|---|---|
| A report or job on a schedule | routine |
| Quiet, read-only monitoring of one personal account | watch |
| A single commitment, reminder or handed-off piece of work | task |
| A supported incoming event with typed steps | workflow trigger |

Give one responsibility one automation. Check `agenticos:list_routines` and `agenticos:list_watches` before adding another poller. Agree the sources, cadence, time zone, audience, permitted actions and when to stay quiet before creating anything.

## Routines

A routine runs a published agent on a cadence with a fixed prompt.

1. `agenticos:list_agents` to pick the agent; `agenticos:list_routines` with its `agent_id` to check for a duplicate.
2. `agenticos:create_routine`.
3. `agenticos:run_routine_now` to show what it produces, schedule untouched.
4. `agenticos:list_routines` to confirm `is_active`, `next_fire_at` and the last run.

Points that decide whether it works:

- **The prompt stands alone.** Each run starts with none of this conversation. Write what to do, from which sources, in which language and what to produce. A weekday schedule that reports "yesterday" skips the weekend: ask whether Monday should cover Friday to Sunday.
- **One cadence.** Either `cron_expression` (five fields, read in `time_zone`, an IANA name) or `every_minutes`. Write the local time as the user said it: 9:00 on weekdays in `Europe/Warsaw` is `0 9 * * 1-5` with that zone.
- **`result_mode`.** `report` produces a report per run. `inbox` creates one working chat and Inbox case per relevant source item and stays quiet on unchanged ones.
- **`answer_to`.** `run_log` keeps results in the routine's log, `primary` uses the person's primary conversation, `conversation` uses `delivery_conversation_id`. For a topic thread, find the chat with `agenticos:list_conversations` or open one with `agenticos:create_conversation`.
- **`runs_as_me`** (the default) fires as the creator, with their memory and personal connections. It needs the `personal:consent` scope; without it the call is refused with "Only you, signed in as yourself, can let a trigger act as you".
- **Platform records.** A prompt that reads runs, spend or tables needs the agent to bind the platform MCP server (`account: "platform"`), and that binding exists only when a person is behind the run. With `runs_as_me: false` such a routine is saved paused with `setup_required`; the user enables Act as creator under `/routines`.
- **Delivery.** `notification_channels` picks where the person is notified; `[]` turns external delivery off. The tool description's recipe for posting to a chat channel names tools this server does not expose, so do not promise channel delivery from here.
- **Bounds.** `ends_at` (ISO with offset) for time-limited requests; `monthly_budget_usd` as a cap; `pinned_version_id` to hold one published version.
- **`setup_required: true`** means the routine was saved paused (`is_active: false`); `setup_issues` says why. Report that, link `/routines`, and repair that routine. Do not create a second one or retry with another agent.

`agenticos:update_routine` changes only what is passed; `active: false` pauses. `agenticos:delete_routine` removes it for good, so prefer pausing unless the user asked to delete.

## Watches

A watch has a published agent check one of the person's own connected accounts, read-only, and report changes.

1. `agenticos:list_my_connections` for the source `connection_id`. If its status is doubtful, `agenticos:test_my_connection`.
   With no connection for the service, stop: find its key with `agenticos:search_mcp_servers` and send the user to `/mcp-servers?connect=<key>` to connect it.
2. Confirm a published agent already binds that personal service: `agenticos:get_agent` shows `draft_spec.mcp_servers` with `account: "personal"` and the service's `catalog_key`. That is the draft, so say that the published version is assumed to match. Do not add a capability or swap in another agent to make it fit.
3. `agenticos:create_watch` with that `agent_id` and `connection_id`, a `title`, `instructions`, `every_minutes` and, when the user gave a duration, `ends_at`. When the request already supplies all of these, create it without further questions.

- The organization sets the minimum cadence and whether watches are allowed. Neither can be read; a shorter `every_minutes` or a disabled feature shows as a refusal.
- `report_mode: "changes"` is quiet until something changes; `every_check` reports each time.
- Creating and editing a watch needs the person's own authority and the `personal:consent` scope. A refusal on that scope is fixed by reauthorizing the MCP client under **Custom**, not by another route.
- `agenticos:update_watch` pauses with `active: false`. Set `review_sources` only when the user re-approves the attached knowledge and context. `agenticos:delete_watch` also removes its findings.

## Tasks

A task is a durable commitment on a managed task board, shared with the console's Tables, Kanban and Inbox views. It is not a scratch plan: create one only when the user means to track something.

1. `agenticos:list_task_boards` for the board's `table_id`. `agenticos:ensure_task_board` creates the missing board for a scope; `private` is the default.
2. `agenticos:create_task`. Set `external_id` for a source item so a retry returns the existing task instead of a duplicate.
3. `agenticos:get_task` for the current `revision`, then `agenticos:update_task` with `expected_revision`. An update replaces every field of the task: one left out is reset (an omitted `assignee_user_id` clears the assignee), so send all the ones to keep.

- `due_at` is only a deadline. `start_at` schedules the action: an Inbox reminder for a person, one agent run for an agent.
- `next_actor` says who moves next. A task created with `assignee_agent_id` defaults to the agent.
- An agent's result waits for the user's review. A prepared draft is not a sent message.
- Mark `done` after the user confirms or an authorized action succeeded, never because a draft exists.
- Share beyond `private` only when the user named the project, group or organization. Do not build a parallel TODO table.

## Organization settings

`agenticos:update_proactivity_settings` (needs `org:settings` and `budgets:manage`) sets whether watches are allowed, their minimum cadence, the daily briefing and the per-person monthly limit for that work. Only passed fields change.
