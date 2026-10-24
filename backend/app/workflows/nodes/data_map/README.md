# data.map

Builds a small, typed record out of earlier outputs. Bind anything to `source`,
then list the fields you want:

| Field | What it is |
|---|---|
| `target_field` | The name the value is stored under in `values` |
| `source_path` | A JMESPath expression over `{"source": ...}`, e.g. `source.payload.email` |
| `coerce_to` | `string`, `number`, `integer`, `boolean`, `json`, `file_ref` or `table_ref` |
| `default` | Used when the expression finds nothing |

A later node binds to one field by path: `values.email`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `source` is bound |
| `out` | output | `DataMapOutput` | `values: dict` |

## Coercion

Coercion is lax, the way a form field is: `"42"` becomes `42`, and `"true"` or
`1` becomes `true`. A value with no reading as the declared type fails the node
with `MAPPING_COERCION_FAILED` and names the field. A node downstream never sees
a value of the wrong type. `json` keeps the value as it is.

## What it deliberately does not do

It does not evaluate code, templates or formulas. The expression language is
JMESPath restricted to pure functions (see `logic.if`), and it is checked when
the graph is validated.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`.
