# code.python.simple

Runs a short Python script in the Monty sandbox. The script reads the bound
values as `args`, and its last expression is the step's `result`. Whatever it
prints comes back as `stdout`, clipped.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `args` is bound |
| `out` | output | `PythonSimpleOutput` | `result`, `stdout` |

## What it can and cannot do

Monty has no filesystem, no network and a small standard library - `math`,
`json`, `datetime`, `re` - so a script can compute and nothing else, within
`timeout_seconds` and `max_memory_mb`. The step is `pure` and `idempotent`. A
script that needs files or packages belongs in `code.python.sandbox`.

## Failures

A result that is not a JSON value - a set, an object, `NaN` - fails with
`PYTHON_OUTPUT_NOT_JSON`. A problem in the script, including running past a
limit, fails with `PYTHON_ERROR` and is not retried, since only a different
script fixes it.
