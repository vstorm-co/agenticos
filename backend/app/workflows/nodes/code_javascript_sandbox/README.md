# code.javascript.sandbox

Runs JavaScript on Node, with the run's files, as a durable job on the
organization's `sandboxd` connection. The script is the body of an async
function: it reads the bound values as `args`, finds its input files in the
folder named by `inputs`, writes files to `outputs`, may `await`, and what it
`return`s is the step's `result`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `args` and `files` are bound |
| `out` | output | `JavaScriptSandboxOutput` | `result`, `stdout_tail`, `log_file`, `output_files` |

## The same job as Python

The job protocol - stage, launch once, check on every later dispatch, measure
and collect - is `_sandbox_job.py`'s, shared with `code.python.sandbox`, so the
isolation, the limits and the retry guarantee are the same. What this step adds
is its runner: `run.js` wraps the script in an async function, reads its return
value back through `JSON.stringify`, and writes the answer and the `done` marker
however the script ended. The runtime has to have Node.

## Failures

A thrown error is `JAVASCRIPT_ERROR`. A result that is no JSON value - a
function, a `BigInt` - is `JAVASCRIPT_OUTPUT_NOT_JSON`; `undefined` answers
`null`. Past `timeout_seconds` it is `JAVASCRIPT_SANDBOX_TIMEOUT`, and over the
output bounds `JAVASCRIPT_OUTPUT_TOO_LARGE`. The host's own failures are
`SANDBOX_UNAVAILABLE` and `SANDBOX_UNREACHABLE`, as for Python.
