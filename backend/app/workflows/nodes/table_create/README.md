# table.create

Creates a new table with a typed schema. It is an administrative step, so record
steps never do this. It needs `tables:create`, checked against the graph's
author at publish and against the run's principal when it runs.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow |
| `out` | output | `TableCreatedOutput` | `table` (a reference), `table_id`, `schema_version`, `columns` by label |

A table's name is unique among the organization's live tables. `name` is
bindable, so a workflow that runs more than once and makes a table each time
can bind a name that differs per run. Otherwise the second run fails with
`ALREADY_EXISTS`.

`effect_kind="write"`, `retry_guarantee="idempotent"`: a retried step returns
the table it already made.
