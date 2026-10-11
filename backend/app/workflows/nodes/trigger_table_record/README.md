# trigger.table_record

A workflow a table record's creation, change or deletion starts. A record added,
changed or deleted - in the console, over the API, by an agent or by another
workflow - that matches every filter starts one run with the record, for each
event the trigger listens for (`events`, added only by default).

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `TableRecordTriggerOutput` | `table_id`, `record_id`, `event`, `values` by column id, `fields` by label, `before` and `changed` for a change or deletion, `author_id` |

Filters hold on the record as added or changed to, or as it was before it was
deleted. A change starts it only when one of the table's chosen columns changed,
when columns are chosen. Publishing a version subscribes the workflow; nothing
done before that starts it. A chain of runs writing into each other's tables
stops at the first trigger it already passed.
