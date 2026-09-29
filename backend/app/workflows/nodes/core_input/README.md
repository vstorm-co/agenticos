# core.input

The manual trigger: a run started by hand, from the HTTP API or over the
workflow-run WebSocket. Named **Manual or API** in the editor; the other ways in
are triggers of their own (`trigger.chat`, `trigger.webhook`, `trigger.schedule`,
`trigger.table_record`). It hands the graph what the run was started with:
`payload` (whatever the invoking surface supplied) and `triggered_by` (which
surface that was: `api`, `chat`, `webhook`, `schedule`, `table_created`, ...).

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `WorkflowInputPayload` | `payload: dict`, `triggered_by: str` |

## Why the payload is untyped

The shape belongs to the caller, not to the node: an API body, a chat message
and a table record's snapshot look nothing alike. A downstream node binds to a
field by path (`payload.question`), and that binding is checked against the
target field when the node is dispatched. A value that does not fit fails the
run with `INVALID_BINDING` instead of reaching the handler as the wrong type.
To coerce or rename fields first, put a `data.map` after this node.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`. It reads the run's frozen
input and nothing else, so running it again gives the same answer.
