# file.read

Reads one of the run's files as UTF-8 `text`, a `json_value` or header-keyed CSV
`rows`, as `parse_as` says. Only that field of the output is set.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `FileReadInput` | `file` |
| `out` | output | `FileReadOutput` | `text`, `json_value` or `rows` |

## What it refuses

The result travels inline to the next step, so a file larger than `max_bytes`
fails with `FILE_TOO_LARGE` before its bytes leave storage. A file that is not
UTF-8, JSON that does not parse, and a CSV row wider or narrower than its header
all fail with `FILE_PARSE_FAILED`, never a partial value. Reading has no side
effect, so the step is `idempotent`.
