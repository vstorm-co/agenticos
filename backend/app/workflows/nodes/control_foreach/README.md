# control.foreach

Runs the steps inside the loop once for every element of a list, one element
at a time and in order, and then continues through `done` with every
iteration's result.

```text
query ─► for each ─body─► loop.item ─► agent.run ─► table.record.update ─► loop.yield
             └─done─► notification.send
```

The body starts at `loop.item`, which provides `item`, `index` and `count` to
bind to, and ends at `loop.yield`, whose bound `value` becomes the iteration's
entry in `results`. Nothing inside the body is connected back to the loop and
nothing inside it connects out of it: the loop continues through its own
`done` port once the last iteration ends. A body node may bind to anything that
ran before the loop. Nothing outside the body may bind to a node inside it;
read the loop's `results` instead.

## The list is frozen

The bound `items` are checked and stored before the first iteration starts.
Every iteration reads that stored copy, so a record changed while the loop
runs does not change what it iterates. A list longer than
`WORKFLOW_FOREACH_MAX_ITEMS` (default 1000) or larger than
`WORKFLOW_FOREACH_MAX_MANIFEST_BYTES` (default 1 MiB) is refused, never
truncated. An empty list gives `results: []` without running the body.

## Iterations are durable

Each iteration's steps run in a scope of their own, `(run, loop, index)`, with
their own attempts, idempotency keys and costs. The next iteration is scheduled
in the same transaction that ends the previous one, so a restart resumes at the
right index without repeating a confirmed write. An approval inside an
iteration resumes that iteration.

## Item-error policy

| `item_error_policy` | A failed iteration |
|---|---|
| `stop` (default) | fails the loop with that error, naming the iteration's scope path |
| `collect` | puts `null` in its `results` slot, records the error in `errors`, and continues |

A failure that no fallback may bypass (revoked access, a spent budget) fails
the run under either policy.

## Limits

Loops nest at most `WORKFLOW_FOREACH_MAX_DEPTH` deep (default 3), checked at
publish. Every node run a run creates counts against
`WORKFLOW_RUN_MAX_NODE_RUNS` (default 10,000), checked as each iteration starts.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `items` is bound |
| `body` | output | none | the edge to the body's `loop.item` |
| `done` | output | `ForeachOutput` | `results`, `errors`, `count` |

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`. The loop has no effect of
its own; its body's steps keep their own guarantees.
