# convert.csv_to_json

Converts a CSV file into a JSON file holding a list of header-keyed rows, and
says how many rows it wrote. The CSV must be UTF-8 with every row as wide as its
header, or the step fails with `FILE_PARSE_FAILED`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `ConvertFileInput` | `file` |
| `out` | output | `ConvertCsvToJsonOutput` | `file`, `row_count` |

It stores a new file on every call, so it is `at_least_once`.
