# core.input

The API trigger: a run started by an HTTP request (`POST /workflow-runs`) or over
the workflow-run WebSocket. Named **API request** in the editor; a run started by
a person clicking Run is `trigger.manual`, and the other ways in are triggers of
their own (`trigger.chat`, `trigger.webhook`, `trigger.schedule`,
`trigger.table_record`). The id stays `core.input`, so every graph written
before the two were split keeps starting from the API. It hands the graph what the run was started with:
`payload` (whatever the invoking surface supplied) and `triggered_by` (which
surface that was: `api`, `chat`, `webhook`, `schedule`, `table_created`, ...).

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `WorkflowInputPayload` | `payload: dict`, `triggered_by: str` |

## Declared fields

With no `fields` configured the payload is untyped: its shape belongs to the
caller. A downstream node binds to a field by path (`payload.question`), and
that binding is checked against the target field when the node is dispatched. A
value that does not fit fails the run with `INVALID_BINDING` instead of reaching
the handler as the wrong type.

Declared `fields` (`TriggerInputConfig`) make the payload a contract. Each has
a `name`, a `type` - `text`, `number`, `integer`, `boolean`, `date` (ISO
`YYYY-MM-DD`) or `choice` among its `options` - and whether it is `required`.
`input_problems` checks a run's input against them strictly before the run is
admitted, and `WorkflowExecutionService.start` refuses one that misses a field,
sends one of the wrong type or sends one not declared, with
`WORKFLOW_RUN_INPUT_INVALID` naming each. `ports_for` types `out`'s `payload` by
them, so a binding to `payload.seats` is checked against its target at publish.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`. It reads the run's frozen
input and nothing else, so running it again gives the same answer.
