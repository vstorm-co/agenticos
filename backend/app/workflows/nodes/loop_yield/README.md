# loop.yield

The last step of every `control.foreach` body. Its bound `value` becomes this
iteration's entry in the loop's `results`, in input order. An iteration whose
branch never reaches it contributes `null`. It has no output port: the loop
continues through its own `done` port once every iteration has ended, so no
edge ever leads back from the body to the loop.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `value` is bound |

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`.
