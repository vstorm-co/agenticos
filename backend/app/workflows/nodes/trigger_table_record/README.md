# trigger.table_record

A workflow a new table record starts. A record added to the table - in the
console, over the API, by an agent or by another workflow - that matches every
filter, as it was added, starts one run with the record.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `TableRecordTriggerOutput` | `table_id`, `record_id`, `values` by column id, `fields` by label, `author_id` |

Publishing a version subscribes the workflow; records added before that never
start it. A chain of runs writing into each other's tables stops at the first
trigger it already passed. An update to a record starts nothing.
