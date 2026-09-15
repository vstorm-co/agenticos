"""Deriving a document's calendar date for the FA-039 `doc_date` filter.

`doc_date` is a pure calendar date stored as ISO `YYYY-MM-DD`. Provenance
precedence: an explicit author/uploader date, else the source's modified time
(connector `modified_at` / file mtime), else ingestion time. Any source
*timestamp* is converted to UTC before its calendar date is taken, so the stored
value never depends on a server's local timezone and the range filter compares
like calendar dates.
"""

from __future__ import annotations

from datetime import UTC, date, datetime


def to_utc_date(value: datetime | date | int | float | None) -> date | None:
    """The UTC calendar date of a timestamp/date, or None for an absent value.

    A naive datetime is read as UTC (the connectors already normalize to UTC);
    an aware one is converted. A POSIX mtime (int/float seconds) is read as UTC.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    return datetime.fromtimestamp(value, UTC).date()


def iso_doc_date(*candidates: datetime | date | int | float | None) -> str:
    """The first available candidate as an ISO `YYYY-MM-DD` date, else today (UTC).

    Candidates are tried in provenance order; the first that resolves to a date
    wins, and ingestion time (now, UTC) is the final fallback so every ingested
    document carries a date.
    """
    for candidate in candidates:
        resolved = to_utc_date(candidate)
        if resolved is not None:
            return resolved.isoformat()
    return datetime.now(UTC).date().isoformat()


__all__ = ["iso_doc_date", "to_utc_date"]
