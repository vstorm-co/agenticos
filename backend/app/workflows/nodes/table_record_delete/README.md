# table.record.delete

Deletes one record. The record's history is kept. Bind `record_id`, and
optionally the `expected_revision` it was read at. Without a revision, the step
deletes the record at its current one.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `record_id`, `expected_revision` are bound |
| `out` | output | `TableRecordDeleteOutput` | `record_id` |

`effect_kind="write"`, `retry_guarantee="idempotent"`: a retried delete that
already succeeded answers with the same record id.
