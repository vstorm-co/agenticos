# core.output

Where a graph answers. Its input is the run's output: the run records it when
this node completes, and the surface that started the run (API, chat, webhook,
WebSocket) delivers it to its caller.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; the answer is bound field by field |

Bindable input fields: `text`, `sources`, `artifacts`, `structured`. All are
optional. An output node with nothing bound gives an empty answer, which is
right for a workflow whose work is a table write.

## Why the shape matches `agent.run`

The most common workflow ends with an agent's answer. With `AgentRunOutput` and
`WorkflowOutputPayload` carrying the same fields, each field binds straight
across and the type check passes with nothing in between.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`. Recording the output
twice records the same value. A graph may have several output nodes on
exclusive branches. If more than one runs, the last one to complete wins.
