"""The parsing the file steps share: CSV rows in and out, UTF-8 text.

A step that reads a file refuses what it cannot read exactly - bytes that are
not UTF-8, a CSV whose rows do not match its header - rather than hand on a
best guess, because the next step would treat the guess as the file.
"""

import csv
import io
from collections.abc import Mapping, Sequence
from typing import Any

CSV = "text/csv"
JSON = "application/json"
TEXT = "text/plain"


# csv's process-global parser setting must not be temporarily changed around
# concurrent conversions. This is the largest supported input; each step checks
# its own byte ceiling before parsing.
csv.field_size_limit(50_000_000)

MAX_CSV_ROWS = 10_000
MAX_CSV_COLUMNS = 1_000
MAX_CSV_CELLS = 1_000_000


class ParseError(ValueError):
    """The bytes are not what the step was asked to read them as."""


def utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError(f"The file is not UTF-8 text (byte {exc.start})") from exc


def csv_rows(text: str) -> tuple[dict[str, str], ...]:
    try:
        return _csv_rows(text)
    except csv.Error as exc:
        raise ParseError("The CSV parser could not read this file") from exc


def _csv_rows(text: str) -> tuple[dict[str, str], ...]:
    """Header-keyed rows, refused when a row has more or fewer fields than the header."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return ()
    if len(header) > MAX_CSV_COLUMNS:
        raise ParseError(f"A CSV holds at most {MAX_CSV_COLUMNS} columns")
    if len(set(header)) != len(header):
        raise ParseError("The CSV header names a column twice")
    rows: list[dict[str, str]] = []
    for number, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != len(header):
            raise ParseError(f"Row {number} has {len(row)} fields, the header has {len(header)}")
        if len(rows) >= MAX_CSV_ROWS or (len(rows) + 1) * len(header) > MAX_CSV_CELLS:
            raise ParseError("The CSV has too many rows or cells")
        rows.append(dict(zip(header, row, strict=True)))
    return tuple(rows)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ParseError("A CSV cell must be text, a number, true, false or empty")


class _CsvBuffer(io.StringIO):
    def __init__(self, max_bytes: int) -> None:
        super().__init__()
        self.remaining = max_bytes

    def write(self, text: str) -> int:
        size = len(text.encode("utf-8"))
        if size > self.remaining:
            raise ParseError("The CSV output exceeds its byte limit")
        self.remaining -= size
        return super().write(text)


def csv_text(rows: Sequence[Mapping[str, Any]], *, max_bytes: int = 25_000_000) -> str:
    """Rows as CSV, with a header of every column in the order it first appears."""
    if len(rows) > MAX_CSV_ROWS:
        raise ParseError(f"A CSV holds at most {MAX_CSV_ROWS} rows")
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for column in row:
            if column not in seen:
                seen.add(column)
                columns.append(column)
                if len(columns) > MAX_CSV_COLUMNS or len(rows) * len(columns) > MAX_CSV_CELLS:
                    raise ParseError("The CSV has too many columns or cells")
    out = _CsvBuffer(max_bytes)
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in columns])
    return out.getvalue()
