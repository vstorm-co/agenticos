# trigger.schedule

A workflow that runs on a clock: every so often, or on a cron expression in UTC.
The cadence and the input every run starts with are this node's configuration;
publishing a version is what schedules it.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `ScheduleTriggerOutput` | `fired_at`, `input` |

A tick that finds the last run still going is skipped rather than stacked, and a
schedule whose member can no longer run the workflow is switched off and audited.
It does not catch up on ticks it missed while the worker was down.
