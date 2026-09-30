# debug.echo

Echoes its input back, unchanged, stamped with the time it ran. The one
required sample node for #1786: it exists to prove the node contract - a
typed config, a typed input, a typed output, a handler returning
`NodeResult` - works end to end with no execution engine yet to call it.

## Why this node and not `core.input`/`core.output`

Those two names are left for a later issue to claim as the real
graph-boundary node kinds it defines. `debug.echo` has no real effect and no
opinion about where a graph begins or ends, so shipping it first claims
nothing a later node would have to work around.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `DebugEchoConfig` | `message: str` |
| `out` | output | `DebugEchoOutput` | `echoed: str`, `received_at: datetime` |

`config_schema` and `input_schema` are the same model on purpose: a graph
author can type a message directly on the node (`config.message`), or bind
another node's output into `in` to override it at run time. A bound `in`
wins when it carries a non-empty message.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`: there is no external
call and nothing to double-execute, so an execution engine may retry it
freely once one exists.

## What this deliberately does not do

Nothing observable outside the graph - no file, no table, no network call. A
node with a real effect is #1789/#1790/#1791/#1792's to add, each following
this same `__init__.py` / `_handler.py` / `README.md` shape.
