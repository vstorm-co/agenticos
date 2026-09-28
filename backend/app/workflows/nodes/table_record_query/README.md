# table.record.query

Reads one page of the pinned table's records, filtered by column conditions and
sorted by `created_at`, `updated_at` or a column.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow |
| `out` | output | `TableRecordPage` | `records`, `has_more` |

A page holds at most 100 records, and `has_more` says whether more match. The
step never reads a whole large table on its own. Bind `skip` to read a later
page. The page is a list a `control.foreach` can walk.

`effect_kind="read"`, `retry_guarantee="idempotent"`.
