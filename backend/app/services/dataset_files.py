"""Dataset cases as CSV and JSONL - the import and export formats.

Both formats carry the same nine fields, named the same way, so a file exported
in one and edited by hand imports back in the other. A CSV row holds the
structured fields (`history`, `expected_tool_calls`, `checks`) as JSON text in
their cells and the tags comma-separated; a JSONL line holds them as JSON.

**An authorized export imports back unchanged.** A public read may instead pass
masked cases: their placeholders disclose no source text and are not runnable
training cases. For unmasked records, two details preserve the round trip:

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

import csv
import io
import json
from collections.abc import Iterable, Iterator
from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.field_errors import field_problems, refused_field
from app.db.models.dataset import DatasetCase
from app.schemas.dataset import DatasetCaseContent, DatasetCaseRead, DatasetFileFormat
from app.services.exporting import CSV_INJECTION_PREFIXES, csv_document, jsonl_document

# Mirrored, in this order, by IMPORT_COLUMNS in the console's import dialog
# (frontend/src/components/datasets/import-columns.ts).
COLUMNS = (
    "input",
    "history",
    "reference_answer",
    "counter_example",
    "expected_tool_calls",
    "order_mode",
    "checks",
    "tags",
    "note",
)
_JSON_COLUMNS = frozenset({"history", "expected_tool_calls", "checks"})
_TEXT_COLUMNS = frozenset({"input", "reference_answer", "counter_example", "note"})

# Refused rows named in one refusal; the rest are counted. A wrong column type fails
# every row, and a thousand identical messages hide the one that says what to fix.
_MAX_REPORTED_ROWS = 20


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


def _sorted(value: dict[str, Any], *, first: str | None = None) -> dict[str, Any]:
    """An object with its keys in a fixed order: `first`, then the rest alphabetically."""
    head = {first: value[first]} if first is not None else {}
    return {**head, **{key: value[key] for key in sorted(value) if key != first}}


def _record(case: DatasetCase | DatasetCaseRead) -> dict[str, Any]:
    """One case as its fields, every object in it with its keys in a fixed order.

    `jsonb` keeps an object's keys in an order of its own, not the order they
    were written in, so an export taken straight off the row would differ from
    the file that was imported and from the next export of a re-import. The
    schema fixes the order of the fields it declares; the keys it leaves open - a
    check's parameters and a tool call's arguments - are sorted.
    """
    # Read as stored, not as a new case would be written: an export of a case an
    # earlier rule accepted must not fail on a rule added since.
    record = DatasetCaseRead.model_validate(case).model_dump(mode="json", include=set(COLUMNS))
    record["checks"] = [_sorted(check, first="type") for check in record["checks"]]
    record["expected_tool_calls"] = [
        {"tool": call["tool"], "args": _sorted(call["args"])}
        for call in record["expected_tool_calls"]
    ]
    return record


def _csv_cell(column: str, value: Any) -> str:
    if column in _JSON_COLUMNS:
        return json.dumps(value, ensure_ascii=False) if value else ""
    if column == "tags":
        return _escape(",".join(value))
    return "" if value is None else _escape(value)


def render(cases: Iterable[DatasetCase | DatasetCaseRead], fmt: DatasetFileFormat) -> str:
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
    if column == "order_mode":
        return raw.strip() or "any"
    value = _unescape(raw)
    if column in _TEXT_COLUMNS and column != "input" and value == "":
        return None
    return value


def _rows(text: str, fmt: DatasetFileFormat) -> Iterator[tuple[int, dict[str, Any] | str]]:
    """The file's records one at a time, each with its line or row number, or a reason
    it is unreadable."""
    if fmt == "jsonl":
        for number, line in enumerate(io.StringIO(text, newline=None), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                yield number, f"Not a JSON object: {exc.msg}"
                continue
            except RecursionError:
                yield number, "The line is nested too deeply"
                continue
            if not isinstance(value, dict):
                yield number, "Each line must be a JSON object"
                continue
            unknown = sorted(set(value) - set(COLUMNS))
            if unknown:
                yield number, f"Unknown fields: {', '.join(unknown)}"
                continue
            yield number, value
        return

    # The `csv` reader's default cell ceiling of 128 KiB is smaller than one case's
    # history may be; no cell can be larger than the file it is in.
    csv.field_size_limit(settings.DATASET_IMPORT_MAX_BYTES)
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
    try:
        for number, row in enumerate(reader, start=1):
            if None in row:
                yield number, "The row has more cells than the header has columns"
                continue
            try:
                record = {
                    column: _from_csv_cell(column, raw)
                    for column, raw in row.items()
                    if raw is not None
                }
            except (json.JSONDecodeError, ValueError) as exc:
                reason = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
                yield number, f"A cell could not be read: {reason}"
                continue
            except RecursionError:
                yield number, "A cell is nested too deeply"
                continue
            yield number, record
    except csv.Error as exc:
        raise refused_field("file", f"The file is not valid CSV: {exc}") from None


def parse(content: bytes, fmt: DatasetFileFormat) -> list[DatasetCaseContent]:
    """Every case in an imported file, or a refusal naming the rows that are wrong.

    All or nothing: a file with one bad row imports none, because a dataset
    silently missing a row is a test suite that passes for the wrong reason.

    Rows are read one at a time and the file is refused at the first row past
    `DATASET_IMPORT_MAX_ROWS`, so its cost is bounded by that limit and not by
    how many rows fit in `DATASET_IMPORT_MAX_BYTES`. CPU-bound: a caller on the
    event loop runs it in a thread.

    Raises:
        BadRequestError: When the file is too large or holds too many rows, is
            not UTF-8, has no rows, or has rows that do not validate. Row problems
            are reported under `rows.<n>`, numbered from the first data row (CSV)
            or line (JSONL).
    """
    max_bytes = settings.DATASET_IMPORT_MAX_BYTES
    if len(content) > max_bytes:
        raise refused_field(
            "file", f"An import is at most {max_bytes / (1024 * 1024):g} MB; split the file"
        )
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise refused_field("file", "The file must be UTF-8 text") from None

    max_rows = settings.DATASET_IMPORT_MAX_ROWS
    cases: list[DatasetCaseContent] = []
    problems: list[dict[str, str]] = []
    refused = 0
    for count, (number, record) in enumerate(_rows(text, fmt), start=1):
        if count > max_rows:
            raise refused_field("file", f"An import holds at most {max_rows} rows; split the file")
        if isinstance(record, str):
            refused += 1
            problems.append({"field": f"rows.{number}", "message": record})
        else:
            try:
                cases.append(DatasetCaseContent.model_validate(record))
            except ValidationError as exc:
                refused += 1
                problems.extend(field_problems(exc.errors(), root=f"rows.{number}"))
        del problems[_MAX_REPORTED_ROWS:]
    if refused:
        raise BadRequestError(
            message=(
                f"{refused} {'row' if refused == 1 else 'rows'} could not be imported, "
                f"so none were. Fix {'it' if refused == 1 else 'them'} and try again."
            ),
            details={"refused_rows": refused, "fields": problems},
        )
    if not cases:
        raise refused_field("file", "The file holds no cases")
    return cases
