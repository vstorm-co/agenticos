# convert.text_to_file

Stores bound `text` as a UTF-8 TXT file of the run - the pair of `text.extract`,
for text that has to travel as a file or is too long to hand on inline.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `ConvertTextToFileInput` | `text` |
| `out` | output | `ConvertTextToFileOutput` | `file` |

It stores a new file on every call, so it is `at_least_once`.
