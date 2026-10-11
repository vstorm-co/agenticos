# logic.merge

Rejoins the two branches of a `logic.if`. Connect the last node of each branch
to its `in` port. It runs once the branch that was taken reaches it, and it
passes that branch's last output on as `value`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | one edge from each branch |
| `out` | output | `LogicMergeOutput` | `value`: the arriving branch's output |

## Why it has no bindings

Neither branch runs on every path to the merge, so a merge may not bind to
either branch's output. A binding may only read from a node that always runs
before it. The branch that ran is known when the merge is dispatched, so the
dispatcher hands the merge that branch's output. A node after the merge reads a
field of `value` by path (`value.text`). That read is checked when the node is
dispatched, because the two branches may produce different shapes.

## What publishing checks

A merge's inputs must leave one `logic.if` through different ports, so exactly
one of them ever runs. Two edges from the same branch, or from the same port,
are refused.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`.
