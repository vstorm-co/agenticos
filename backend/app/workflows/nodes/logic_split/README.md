# logic.split

**Split**: send the run down several branches at once. Each branch has a name - the
branch's port - and everything wired to a branch runs beside what is wired to the
others. Every branch is always taken, so a Split has no condition.

## Why it exists

A port can already feed several steps, but the branches of one port are not named
and cannot be told apart on the canvas. A Split names them, and the editor draws them
as the parallel branches they are.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | - | the run, nothing bound |
| one per branch | output | - | nothing: steps in a branch bind to what ran before the Split |

## What it deliberately does not do

- It does not race its branches or take the first to finish: every branch runs, and
  a step that waits for them waits for all (a **Merge** with *Wait for all branches*,
  or any step whose inputs are the branches).
- It cannot route its errors: it fails only before any branch has started.
- It is not a loop scope. Its id is outside `control.*`, so publishing derives no body
  for it.

## What publishing checks

A step fed by several branches runs once every step before it has settled, if any wire into
it is live, so it is not refused. A **Merge** is judged by how its branches reach it: waiting
for all branches, each must be certain to arrive whenever the merge runs (an If with a way
out that leads elsewhere is refused, naming the branch). Two **Output** steps, or two
**Respond to webhook** steps, that can both run in one run are refused.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`.
