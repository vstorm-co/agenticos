# logic.merge

Joins branches back into one path. It has two modes, set with **Wait for**:

- **The branch that ran** (the default, `wait_for: one`): for the branches of a step that
  takes a single way out, such as an If, a Switch, a decision, a classifier, an approval,
  an error handler or a table check. Connect the last node of each branch to its `in`
  port. It runs once the branch that was taken reaches it, and passes that branch's last
  output on as `value`.
- **Every branch** (`wait_for: all`): for branches that run side by side, such as a
  Split's. It runs once all of them have settled and passes each one's output on by name
  as `branches`. A step after it reads `branches.<name>.<field>`.

A config with no `wait_for` is the first mode, so a merge saved before the second existed
behaves as it did.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | one edge from each branch |
| `out` | output | `LogicMergeOutput` | `value`: the arriving branch's output, or `branches`: every branch's output by name |

## Branch names

Each incoming branch has a name in `branches`: the one set in `branch_keys`, else the
Split's branch name, else a name made from the step the branch leaves. Names must differ,
and a read of a name no branch has is refused when publishing.

## Why it has no bindings

No branch runs on every path to a merge that waits for the branch that ran, so such a
merge may not bind to any branch's output. A binding may only read from a node that
always runs before it. The branch that ran is known when the merge is dispatched, so the
dispatcher hands the merge that branch's output. A node after the merge reads a field of
`value` by path (`value.text`). That read is checked when the node is dispatched, because
the two branches may produce different shapes.

After a merge that waits for every branch all of them ran, so a step after it may also
bind to a branch's own output directly, not only through `branches`.

## What publishing checks

Whether two branches can run in one run is worked out from the graph (a Split's legs can; the
arms of an If cannot, however they are nested or share steps).

- Waiting for the branch that ran: no two branches may be able to run together. If some can,
  publishing says so, and hints at **Wait for all branches** only when that would be valid.
  Two edges from the same branch, or from the same port, are refused.
- Waiting for every branch: some branches must be able to run together, and each must be
  certain to arrive whenever the merge runs, else the merge is refused naming the branch.
  Each branch must have its own name.

## Limits

The output of every branch is held in one result, so a merge that waits for all is subject
to the inline result cap like any other step.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`.
