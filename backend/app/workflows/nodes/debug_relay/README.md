# debug.relay

Takes what `debug.echo` emits and hands it on as what `debug.echo` reads. It
exists so a graph can hold two connected steps before any real node does:
`debug.echo` -> `debug.relay` -> `debug.echo`, or a Relay wired between any pair.

## Why a second sample node

`debug.echo` alone cannot be chained. An edge is valid only when the source and
target ports carry the same shape, and Echo's `out` (`echoed`, `received_at`)
is not Echo's `in` (`message`). Relay is the adapter that closes the loop; the
workflow templates the editor ships are built from the pair.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `DebugEchoOutput` | `echoed: str`, `received_at: datetime` |
| `out` | output | `DebugEchoConfig` | `message: str` |

Both schemas are Echo's own models, imported rather than copied, so the shapes
match by construction. `in` is a data input: bind `echoed` and `received_at` to
an Echo's output fields. Relay has no configuration.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`, as for Echo: no external
call and nothing to double-execute.

## What this deliberately does not do

Anything observable outside the graph. An unbound input answers `Failed`
(`RELAY_INPUT_MISSING`) rather than relaying an invented empty message.
