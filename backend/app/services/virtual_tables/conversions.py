"""Changing a column's type: which changes keep values meaningful, and the value each becomes.

A type change rewrites every record's value for the column, so it is offered only
where a value of the old type reads as one of the new: any value can become text,
text can become a number, a date or a choice when it says one, a whole number is a
number, and a choice can become several. A change some value does not survive is
refused as a whole, naming how many and one example - the person fixes those
values, or adds a new column - rather than leaving records holding a value their
column no longer accepts.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.schemas.virtual_table import CellValue, ColumnDef, ColumnTypeName
from app.services.virtual_tables.types import COLUMN_TYPES, CellProblem

_TEXTS: frozenset[ColumnTypeName] = frozenset({"text", "long_text"})

CONVERSIONS: dict[ColumnTypeName, frozenset[ColumnTypeName]] = {
    "text": frozenset(
        {"long_text", "number", "integer", "boolean", "date", "datetime", "single_select"}
    ),
    "long_text": frozenset({"text", "number", "integer", "boolean", "date", "datetime"}),
    "number": frozenset({"text", "long_text", "integer"}),
    "integer": frozenset({"text", "long_text", "number"}),
    "boolean": frozenset({"text", "long_text"}),
    "date": frozenset({"text", "long_text", "datetime"}),
    "datetime": frozenset({"text", "long_text"}),
    "single_select": frozenset({"text", "long_text", "multi_select"}),
    "multi_select": frozenset({"text", "long_text", "single_select"}),
}
"""What each type may become. Anything else - a date to a number, a yes/no to a
date - has no reading a person would agree with, and is refused."""

_INTEGER = re.compile(r"[+-]?\d+")
_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")
_YES = frozenset({"true", "yes", "y", "1"})
_NO = frozenset({"false", "no", "n", "0"})


def convertible(old: ColumnTypeName, new: ColumnTypeName) -> bool:
    """Whether a column of type `old` may become `new`."""
    return new in CONVERSIONS[old]


def _label(column: ColumnDef, option_id: object) -> str:
    """An option's label - an archived one too, since a record may still hold it."""
    for option in column.options:
        if str(option.id) == option_id:
            return option.label
    raise CellProblem("That is not one of the column's options")


def _as_text(value: object, column: ColumnDef) -> str:
    """A value of `column` written out as a person reads it."""
    if column.type == "boolean":
        return "true" if value else "false"
    if column.type == "single_select":
        return _label(column, value)
    if column.type == "multi_select":
        return ", ".join(_label(column, item) for item in value) if isinstance(value, list) else ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _from_text(text: str, column: ColumnDef) -> object:
    """What text says as a value of `column`, for its validator to hold to its rules."""
    if column.type == "integer":
        if not _INTEGER.fullmatch(text):
            raise CellProblem("Expected a whole number")
        return int(text)
    if column.type == "number":
        if not _NUMBER.fullmatch(text):
            raise CellProblem("Expected a number")
        return int(text) if _INTEGER.fullmatch(text) else float(text)
    if column.type == "boolean":
        lowered = text.lower()
        if lowered in _YES:
            return True
        if lowered in _NO:
            return False
        raise CellProblem("Expected yes or no")
    if column.type == "datetime":
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            raise CellProblem("Expected an ISO 8601 timestamp") from None
        # Text names no zone more often than not; it is read as UTC, as a date is.
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).isoformat()
    if column.type == "single_select":
        for option in column.options:
            if option.label == text and not option.archived:
                return str(option.id)
        raise CellProblem("That is not one of the column's options")
    return text


def convert(value: CellValue, old: ColumnDef, new: ColumnDef) -> CellValue:
    """The value a cell of `old` holds once its column is `new`, or :class:`CellProblem`.

    Empty text becomes no value at all, which is what an empty cell of a number or
    a date is.
    """
    if value is None:
        return None
    if new.type in _TEXTS:
        converted: object = _as_text(value, old)
    elif old.type in _TEXTS:
        text = str(value).strip()
        if not text:
            return None
        converted = _from_text(text, new)
    elif old.type == "date":
        converted = f"{value}T00:00:00+00:00"
    elif old.type == "single_select":
        converted = [value]
    elif old.type == "multi_select":
        chosen = value if isinstance(value, list) else []
        if len(chosen) > 1:
            raise CellProblem("Holds more than one choice")
        if not chosen:
            return None
        converted = chosen[0]
    else:
        # A number becoming the other kind of number: its validator decides.
        converted = value
    return COLUMN_TYPES[new.type].validate(converted, new, True)


def option_labels(values: list[CellValue]) -> list[str]:
    """The distinct texts a column holds, in first-seen order - the choices it becomes."""
    seen: dict[str, None] = {}
    for value in values:
        if isinstance(value, str) and value.strip():
            seen.setdefault(value.strip(), None)
    return list(seen)
