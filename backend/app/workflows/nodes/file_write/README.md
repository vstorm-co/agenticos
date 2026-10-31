# file.write

Stores bound `text`, a `json_value` or `rows` as a new UTF-8 file of the run, in
the `format` its config names, and returns it as a `FileRef`. Rows become CSV
with a header of every key in the order it first appears.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `FileWriteInput` | `text`, `json_value` or `rows` |
| `out` | output | `FileWriteOutput` | `file` |

## What it refuses

A format with nothing bound to write fails with `FILE_WRITE_FAILED` rather than
store an empty file, and so does a CSV cell that is an object or a list. A file
over 25 MB is `FILE_TOO_LARGE`. Every call stores a new file, so the step is
`at_least_once`.
