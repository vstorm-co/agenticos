# table.record.get

Reads one record by a bound `record_id` or `external_id`. Bind exactly one of
them.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `record_id` or `external_id` is bound |
| `out` | output | `TableRecordLookup` | `found`, and `record` when it exists |

A record that does not exist is `found: false`, not a failure. Branch on it
with `logic.if` and the condition `value.found`.

`effect_kind="read"`, `retry_guarantee="idempotent"`.
