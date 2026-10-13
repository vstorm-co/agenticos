"""Dataset cases as CSV and JSONL - the import and export formats.

Both formats carry the same nine fields, named the same way, so a file exported
in one and edited by hand imports back in the other. A CSV row holds the
structured fields (`history`, `expected_tool_calls`, `checks`) as JSON text in
their cells and the tags comma-separated; a JSONL line holds them as JSON.

**An export imports back unchanged.** That is the contract this module is
written to, and it decides two things a plain export would get wrong:

- An empty field is an empty cell, never `null`, `[]` or `None`, and an empty
  cell reads back as the field's empty value.
- The spreadsheet formula guard is reversible. A cell opening on `=`, `+`, `-`,
  `@`, a tab or a carriage return is prefixed with `'` so a spreadsheet does not
  evaluate it, and so is a cell already opening on `'` - which is what lets an
  import drop exactly one leading `'` and get the original text back.

Ids, sources and versions are not columns: an import appends new cases, so a
column naming which case a row was would describe something the import does not
do.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.core.field_errors import field_problems, refused_field
from app.db.models.dataset import DatasetCase
from app.schemas.dataset import DatasetCaseContent, DatasetFileFormat
from app.services.exporting import CSV_INJECTION_PREFIXES, csv_document, jsonl_document

COLUMNS = (
    "input",
    "history",
    "reference_answer",
    "counter_example",
    "expected_tool_calls",
    "tool_calls_ordered",
    "checks",
    "tags",
    "note",
)
_JSON_COLUMNS = frozenset({"history", "expected_tool_calls", "checks"})
_TEXT_COLUMNS = frozenset({"input", "reference_answer", "counter_example", "note"})

# The largest file an import reads. Ten thousand cases of ordinary length fit with
# room to spare; a file past it is a dataset to split, not a request to raise.
MAX_IMPORT_BYTES = 10 * 1024 * 1024
# How many refused rows one refusal names. The rest are counted, not listed: a
# file with a wrong column type is wrong on every row, and a thousand identical
# messages hide the one that says what to fix.
_MAX_REPORTED_ROWS = 20

# A cell's ceiling for the `csv` reader, whose default of 128 KiB is smaller than
# one case's history may be. No cell can be larger than the file it is in.
_CELL_LIMIT = MAX_IMPORT_BYTES

_TRUE = frozenset({"true", "1", "yes"})
_FALSE = frozenset({"false", "0", "no", ""})


def format_of(filename: str | None, declared: DatasetFileFormat | None) -> DatasetFileFormat:
    """Which format a file is in: the one declared, else its extension.

    Raises:
        BadRequestError: When neither says. Guessing from the content would read
            a one-column CSV as broken JSONL.
    """
    if declared is not None:
        return declared
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return "csv"
    if name.endswith((".jsonl", ".ndjson")):
        return "jsonl"
    raise refused_field("file", "Import a .csv or a .jsonl file, or say which format it is in")


def _escape(value: str) -> str:
    if value and (value[0] in CSV_INJECTION_PREFIXES or value[0] == "'"):
        return "'" + value
    return value


def _unescape(value: str) -> str:
    return value[1:] if value.startswith("'") else value


def _record(case: DatasetCase) -> dict[str, Any]:
    """One case as its fields, in the order the schema declares them.

    Through the schema rather than straight off the row: `jsonb` stores an
    object's keys in its own order, so a tool call written `{"tool", "args"}`
    comes back `{"args", "tool"}`, and an export has to be the same text every
    time it is taken.
    """
    content = DatasetCaseContent.model_validate(case, from_attributes=True)
    return content.model_dump(mode="json")


def _csv_cell(column: str, value: Any) -> str:
    if column in _JSON_COLUMNS:
        return json.dumps(value, ensure_ascii=False) if value else ""
    if column == "tags":
        return _escape(",".join(value))
    if column == "tool_calls_ordered":
        return "true" if value else "false"
    return "" if value is None else _escape(value)


def render(cases: Iterable[DatasetCase], fmt: DatasetFileFormat) -> str:
    """Cases as a whole CSV or JSONL document, in the order given."""
    records = [_record(case) for case in cases]
    if fmt == "jsonl":
        return jsonl_document(records)
    # `csv_document` runs its own formula guard over every cell; the cells are
    # escaped already, and its guard is a no-op on a string that opens on `'`.
    return csv_document(
        list(COLUMNS),
        [[_csv_cell(column, record[column]) for column in COLUMNS] for record in records],
    )


def _from_csv_cell(column: str, raw: str) -> Any:
    if column in _JSON_COLUMNS:
        return json.loads(raw) if raw.strip() else []
    if column == "tags":
        return [tag for tag in _unescape(raw).split(",") if tag.strip()]
    if column == "tool_calls_ordered":
        word = raw.strip().lower()
        if word in _TRUE:
            return True
        if word in _FALSE:
            return False
        raise ValueError("Write true or false")
    value = _unescape(raw)
    if column in _TEXT_COLUMNS and column != "input" and value == "":
        return None
    return value


def _rows(text: str, fmt: DatasetFileFormat) -> list[tuple[int, dict[str, Any] | str]]:
    """The file's records, each with its line or row number, or a reason it is unreadable."""
    if fmt == "jsonl":
        records: list[tuple[int, dict[str, Any] | str]] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                records.append((number, f"Not a JSON object: {exc.msg}"))
                continue
            if not isinstance(value, dict):
                records.append((number, "Each line must be a JSON object"))
                continue
            unknown = sorted(set(value) - set(COLUMNS))
            if unknown:
                records.append((number, f"Unknown fields: {', '.join(unknown)}"))
                continue
            records.append((number, value))
        return records

    csv.field_size_limit(_CELL_LIMIT)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = reader.fieldnames or []
    unknown = sorted(set(header) - set(COLUMNS))
    if unknown or "input" not in header:
        raise refused_field(
            "file",
            "The first row must name the columns: input, and any of "
            + ", ".join(COLUMNS[1:])
            + (f". Not a column: {', '.join(unknown)}" if unknown else ""),
        )
    rows: list[tuple[int, dict[str, Any] | str]] = []
    try:
        for number, row in enumerate(reader, start=1):
            if None in row:
                rows.append((number, "The row has more cells than the header has columns"))
                continue
            try:
                rows.append(
                    (
                        number,
                        {
                            column: _from_csv_cell(column, raw)
                            for column, raw in row.items()
                            if raw is not None
                        },
                    )
                )
            except (json.JSONDecodeError, ValueError) as exc:
                reason = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
                rows.append((number, f"A cell could not be read: {reason}"))
    except csv.Error as exc:
        raise refused_field("file", f"The file is not valid CSV: {exc}") from None
    return rows


def parse(content: bytes, fmt: DatasetFileFormat) -> list[DatasetCaseContent]:
    """Every case in an imported file, or a refusal naming the rows that are wrong.

    All or nothing: a file with one bad row imports none, because a dataset
    silently missing a row is a test suite that passes for the wrong reason.

    Raises:
        BadRequestError: When the file is too large, is not UTF-8, has no rows,
            or has rows that do not validate. Row problems are reported under
            `rows.<n>`, numbered from the first data row (CSV) or line (JSONL).
    """
    if len(content) > MAX_IMPORT_BYTES:
        raise refused_field(
            "file", f"An import is at most {MAX_IMPORT_BYTES // (1024 * 1024)} MB; split the file"
        )
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise refused_field("file", "The file must be UTF-8 text") from None

    cases: list[DatasetCaseContent] = []
    problems: list[dict[str, str]] = []
    refused = 0
    for number, record in _rows(text, fmt):
        if isinstance(record, str):
            refused += 1
            problems.append({"field": f"rows.{number}", "message": record})
            continue
        try:
            cases.append(DatasetCaseContent.model_validate(record))
        except ValidationError as exc:
            refused += 1
            problems.extend(field_problems(exc.errors(), root=f"rows.{number}"))
    if refused:
        raise BadRequestError(
            message=f"{refused} rows could not be imported, so none were. Fix them and try again.",
            details={"refused_rows": refused, "fields": problems[:_MAX_REPORTED_ROWS]},
        )
    if not cases:
        raise refused_field("file", "The file holds no cases")
    return cases
