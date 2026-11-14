# loop.item

The first step of every `control.foreach` body: nothing is wired into it, and
each iteration starts here because it is the body's item step. It provides the current element as `item`, its position as
`index` (from 0) and the list's length as `count`, and every step in the body
binds to those fields.

It is never dispatched. When an iteration starts, the dispatcher records this
step as already succeeded with those three fields, in the same transaction
that ended the previous iteration. It exists only inside a loop body, and it
takes no policy.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `LoopItemOutput` | `item`, `index`, `count` |
