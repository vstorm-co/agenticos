# convert.json_to_csv

Converts a JSON file holding a list of flat objects into a CSV file, with a
header of every key in the order it first appears.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `ConvertFileInput` | `file` |
| `out` | output | `ConvertJsonToCsvOutput` | `file`, `row_count` |

## What it refuses

Only a list of objects whose values are text, numbers, true, false or null is
tabular. An object, a nested list or a row holding an object fails with
`NOT_TABULAR`, never a guessed flattening. It stores a new file on every call,
so it is `at_least_once`.
