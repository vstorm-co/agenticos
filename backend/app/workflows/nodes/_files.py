"""The parsing the file steps share: CSV rows in and out, UTF-8 text.

A step that reads a file refuses what it cannot read exactly - bytes that are
not UTF-8, a CSV whose rows do not match its header - rather than hand on a
best guess, because the next step would treat the guess as the file.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from typing import Any

CSV = "text/csv"
JSON = "application/json"
TEXT = "text/plain"


class ParseError(ValueError):
    """The bytes are not what the step was asked to read them as."""


def utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError(f"The file is not UTF-8 text (byte {exc.start})") from exc


def csv_rows(text: str) -> tuple[dict[str, str], ...]:
    """Header-keyed rows, refused when a row has more or fewer fields than the header."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return ()
    if len(set(header)) != len(header):
        raise ParseError("The CSV header names a column twice")
    rows: list[dict[str, str]] = []
    for number, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != len(header):
            raise ParseError(f"Row {number} has {len(row)} fields, the header has {len(header)}")
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


def csv_text(rows: Sequence[Mapping[str, Any]]) -> str:
    """Rows as CSV, with a header of every column in the order it first appears."""
    columns: list[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in columns])
    return out.getvalue()
