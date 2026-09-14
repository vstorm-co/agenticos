"""Shared primitives for bulk exports - the machinery, not the domain.

`run_export` (runs, approvals, spend) and the audit export both turn a bounded
read into a downloadable document, and each faces the same questions: a
spreadsheet that reads a leading `=` as a formula, a bulk read with no natural
ceiling, a date range that must be given rather than assumed. The answers live
here so the two cannot drift apart, and a third export starts from them rather
than from a copy.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.exceptions import ExportTooLargeError, ValidationError

# The most rows one export may return. A bulk read has no natural ceiling, so this
# is the one by design: the whole body is built in memory on the request's own
# session, which is what lets an audit entry of the export commit before the
# response is written. Above it the request is refused, never trimmed - a
# truncated document is worse than a refused one, because whatever reads it takes
# the partial set for the whole.
MAX_EXPORT_ROWS = 10_000

# A leading one of these turns a CSV cell into a formula in Excel and Sheets, so a
# value that opens with one is prefixed with a quote. A figure never starts with
# one; a name, a note or a tool argument can.
CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class ExportResult:
    """A finished export body and the name it should download as.

    Attributes:
        content: The whole document - a CSV or a JSONL text.
        filename: What the browser saves it as, stamped with the export instant.
        row_count: How many data rows it holds, for the audit entry and the tests.
    """

    content: str
    filename: str
    row_count: int


def escape(value: str) -> str:
    """Neutralise a cell a spreadsheet would otherwise read as a formula."""
    if value and value[0] in CSV_INJECTION_PREFIXES:
        return "'" + value
    return value


def cell(value: object) -> str:
    """One value as CSV text, with `None` an empty cell rather than the word "None".

    The injection guard runs on strings alone. A number rendered as text stays a
    number a spreadsheet can sum, so a negative figure exports as `-1.50` and not
    the quoted `'-1.50` a leading `-` would otherwise earn - the guard exists for
    a name or a tool argument, never for a figure.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return escape(value)
    return str(value)


def csv_document(header: list[str], rows: list[list[object]]) -> str:
    """Header plus rows as one RFC 4180 document, quoting and escaping via `csv`."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([cell(value) for value in row])
    return buffer.getvalue()


def _json_default(value: Any) -> str:
    """Render the types a stored row holds that JSON has no form for.

    A `datetime`, a `UUID` and a `Decimal` all become strings - the same shapes
    the CSV cell uses - so the two documents describe one row the same way. Anything
    else is a bug in what was handed in, not a value to coerce silently.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID | Decimal):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def jsonl_document(records: list[dict[str, Any]]) -> str:
    """One JSON object per line - the form a log pipeline ingests row by row.

    The machine-readable counterpart to the CSV: no injection guard, because
    nothing reads a JSON string value as a formula, and each value keeps its own
    type rather than flattening to a cell. A trailing newline so the last record
    is a complete line, and an empty string for no records rather than a lone
    newline.
    """
    if not records:
        return ""
    lines = [json.dumps(record, default=_json_default, ensure_ascii=False) for record in records]
    return "\n".join(lines) + "\n"


def require_range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    """The window, or a refusal naming the bound that is missing.

    Returns the two bounds narrowed to non-null, so a caller that needs a concrete
    window reads it off the result rather than re-checking what this already proved.

    Raises:
        ValidationError: When either end is absent, or when the start is later than
            the end. A range is what bounds the read; without one an export is the
            whole table, and a reversed one is an impossible predicate that returns
            a silently-empty file and records a misleading export.
    """
    if start is None or end is None:
        missing = [name for name, value in (("from", start), ("to", end)) if value is None]
        raise ValidationError(
            message="An export needs a date range - pass both a start and an end.",
            details={"missing": missing},
        )
    if start > end:
        raise ValidationError(
            message="An export's start must be on or before its end.",
            details={"from": start.isoformat(), "to": end.isoformat()},
        )
    return start, end


def guard_cap(total: int, *, remedy: str) -> None:
    """Refuse above the row cap rather than truncate to it.

    The `remedy` is the one sentence of advice that actually shrinks *this*
    export's match, so a caller is never sent to a control that would not help.

    Raises:
        ExportTooLargeError: When the match exceeds :data:`MAX_EXPORT_ROWS`. The
            message names both numbers and carries the export's own remedy.
    """
    if total > MAX_EXPORT_ROWS:
        raise ExportTooLargeError(
            message=(
                f"This export matches {total} rows, more than the "
                f"{MAX_EXPORT_ROWS} an export may return. {remedy}"
            ),
            details={"row_count": total, "max_rows": MAX_EXPORT_ROWS},
        )


def stamp(kind: str, now: datetime, ext: str) -> str:
    """A download name stamped with the export instant: `<kind>_export_<ts>.<ext>`."""
    return f"{kind}_export_{now.strftime('%Y%m%d_%H%M%S')}.{ext}"
