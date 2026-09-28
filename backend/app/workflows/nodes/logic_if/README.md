# logic.if

Continues the run down one of two branches. The condition is a JMESPath
expression over `{"value": <the bound value>}`, read for truthiness: null,
`false` and an empty string, list or object are false, and anything else is
true.

```text
value.status == 'approved'
length(value.sources) > `0`
contains(value.tags, 'urgent')
```

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `value` is bound |
| `true` | output | `LogicIfOutput` | `branch: "true"`, `value` |
| `false` | output | `LogicIfOutput` | `branch: "false"`, `value` |

Only the edges leaving the chosen port are followed. Every node on the other
branch is recorded as `skipped`, up to the `logic.merge` that rejoins the two
branches. Publishing checks that a merge's inputs come from two different ports
of one `logic.if`, so they can never both run.

## What the expression can do

It can select, filter and compare values, and call a fixed set of pure
functions (`length`, `contains`, `starts_with`, `to_number` and a few others).
It cannot assign, loop or call anything else, so a workflow never executes
code. A function outside the set, or an expression that does not parse, is
refused when the graph is validated. A condition that fails on its data
(`length()` given a number) fails the node rather than picking a branch.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`.
