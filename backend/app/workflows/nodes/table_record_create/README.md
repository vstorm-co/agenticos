# table.record.create

Adds a record to the table the step pins. Bind `values`, keyed by column id or
by column label, and optionally `external_id`, your own key for the record.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `values` and `external_id` are bound |
| `out` | output | `TableRecordOutput` | `record_id`, `external_id`, `revision`, `values`, `fields` |

A value that does not fit its column fails with `INVALID_RECORD`, and a key that
names no live column fails with `UNKNOWN_COLUMN`. A taken `external_id` fails
with `ALREADY_EXISTS`. Publishing refuses a table the graph's author cannot
write, and every run checks the run's principal again.

`effect_kind="write"`, `retry_guarantee="idempotent"`: the write carries the
step's operation key, so a retried step returns the record it already added.
