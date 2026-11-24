# data.value

Holds one value - an object, a list, or a single number, text or boolean - so
later steps can read it. Type the value in as JSON, or bind it whole from an
earlier output. The step hands it on unchanged as `value`.

A later step binds to the whole value, or to a path into it: `value.limit`,
`value.customers`.

## Set once, never overwritten

A step's output is fixed when the step completes. No later step can change it,
so `data.value` is a named constant for the run, not a variable. To build a new
value from it, add a step that reads it - `transform.edit_fields`, `data.map`
or another `data.value` - and bind later steps to that one. To collect values
across the items of a loop, use `loop.yield`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `value` is bound |
| `out` | output | `DataValueOutput` | `value: JsonValue` |

## Errors

`value` is required: publishing refuses a graph where it is not bound. A draft
run of a step with no value fails with `DATA_NOT_SET`. A value over the step
output limit (`WORKFLOW_NODE_MAX_OUTPUT_BYTES`) fails the step like any other
output that is too large.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`.
