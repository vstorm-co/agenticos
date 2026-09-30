# table.record.upsert

Writes the record with a bound `external_id`: it creates the record when no
record holds that key, and updates it when one does. Values are bound, keyed by
column id or label.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `external_id` and `values` are bound |
| `out` | output | `TableRecordOutput` | the record as written, and `created` |

An update writes against the revision the record is at when the step runs. A
record changed between that read and the write fails with `REVISION_CONFLICT`,
which is retried, and the retry reads again.

`effect_kind="write"`, `retry_guarantee="idempotent"`: the write carries the
step's operation key.
