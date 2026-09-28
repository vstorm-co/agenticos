# table.record.update

Changes some of one record's cells. Bind `record_id`, the `values` to change
(`null` clears one), and optionally `expected_revision`.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `record_id`, `values`, `expected_revision` are bound |
| `out` | output | `TableRecordOutput` | the record as written, with its new revision |

With `expected_revision`, a record changed since it was read fails with
`REVISION_CONFLICT`. Without it, the step writes against the record's current
revision.

A workflow that a new record triggered (see table triggers) can update that
record here without firing its own trigger again: an update is not a creation.

`effect_kind="write"`, `retry_guarantee="idempotent"`.
