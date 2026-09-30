# code.python.sandbox

Runs full Python, with packages and the run's files, as a durable job on the
organization's `sandboxd` connection. The script reads the bound values as
`args`, finds its input files in the folder named by `inputs`, writes files to
`outputs`, and sets `result` to its answer.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `args` and `files` are bound |
| `out` | output | `PythonSandboxOutput` | `result`, `stdout_tail`, `log_file`, `output_files` |

## A job, not a call

The first dispatch stages the inputs and starts the script in the background.
Every later one checks on it, so a worker that restarts, or a retry, finds the
same session: it is named after the step's stable operation key. A launch is
proven by the `job.pid` it writes, so a crash between staging and starting is
completed rather than waited on. Checking before launching is what makes the step
`idempotent`.

## Isolation and limits

Only `args`, the input files and the script are staged. No platform credential,
token or vault secret is ever placed in the sandbox. What the script can reach
beyond that is the runtime's own configuration on the host: use a runtime with
no network for untrusted work. CPU, memory, processes and `/tmp` are the
runtime's per-sandbox limits, and `timeout_seconds` bounds the job's whole wall
clock. Past it the session is purged and the step fails with
`PYTHON_SANDBOX_TIMEOUT`.

## Output

The full log is stored as `log_file` and only its tail travels inline. At most
20 output files and 100 MB are imported, and each gets the type its bytes show.
A result that is not a JSON value is `PYTHON_OUTPUT_NOT_JSON`, and an exception
in the script `PYTHON_ERROR`.
