"""The column-type registry: what a cell of each type may hold, and how it is queried.

Everything type-specific lives here and nowhere else, so adding a type is one
entry in :data:`COLUMN_TYPES`. The rest of the service asks the registry three
questions about a column:

- may this value be stored? (:func:`validate_cell`, and :func:`validate_default`
  for a column's default)
- which operators may filter it, and what may the operand be?
  (:func:`validate_filter`)
- can it be sorted, and how does the database read it? (`ColumnType.sortable`,
  `ColumnType.kind`)

A value that does not fit raises :class:`CellProblem`, whose message is written
for the person who typed it. The caller decides which field it is reported
against.

Text is never trimmed or normalized here: a cell is the user's data. The only
text rules are a length ceiling and refusing NUL, which PostgreSQL cannot store
in a JSONB string and would otherwise surface as a 500.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from app.repositories.virtual_table import SqlKind
from app.schemas.virtual_table import CellValue, ColumnDef, ColumnTypeName, FilterOp, FilterValue

MAX_TEXT = 1_000
MAX_LONG_TEXT = 100_000
MAX_INTEGER = 2**53 - 1
"""The largest integer a JavaScript client can hold exactly, which the API shares with them."""

MAX_IN_OPERANDS = 100

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class CellProblem(ValueError):
    """A value does not fit its column. The message is safe to show the user."""


_ORDERED: frozenset[FilterOp] = frozenset({"eq", "ne", "lt", "lte", "gt", "gte", "in", "is_null"})
_TEXTUAL: frozenset[FilterOp] = frozenset({"eq", "ne", "contains", "starts_with", "in", "is_null"})
_EQUALITY: frozenset[FilterOp] = frozenset({"eq", "ne", "is_null"})

Validator = Callable[[object, ColumnDef, bool], CellValue]


@dataclass(frozen=True)
class ColumnType:
    """One entry of the registry."""

    name: ColumnTypeName
    kind: SqlKind
    filter_ops: frozenset[FilterOp]
    sortable: bool
    validate: Validator
    """`(value, column, writing) -> stored value`. `writing` is false for a filter
    operand, which may name an archived select option that a write may not."""


def _text_of(limit: int) -> Validator:
    def validate(value: object, column: ColumnDef, writing: bool) -> CellValue:
        if not isinstance(value, str):
            raise CellProblem("Expected text")
        if "\x00" in value:
            raise CellProblem("Text cannot contain a NUL character")
        if len(value) > limit:
            raise CellProblem(f"Text is longer than {limit} characters")
        return value

    return validate


def _number(value: object, column: ColumnDef, writing: bool) -> CellValue:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CellProblem("Expected a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise CellProblem("Expected a finite number")
    return value


def _integer(value: object, column: ColumnDef, writing: bool) -> CellValue:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CellProblem("Expected a whole number")
    if isinstance(value, float):
        if not value.is_integer():
            raise CellProblem("Expected a whole number")
        value = int(value)
    if abs(value) > MAX_INTEGER:
        raise CellProblem(f"Whole numbers are limited to +/-{MAX_INTEGER}")
    return value


def _boolean(value: object, column: ColumnDef, writing: bool) -> CellValue:
    if not isinstance(value, bool):
        raise CellProblem("Expected true or false")
    return value


def _date(value: object, column: ColumnDef, writing: bool) -> CellValue:
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise CellProblem("Expected a date as YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise CellProblem("Expected a real calendar date") from None
    return value


def _datetime(value: object, column: ColumnDef, writing: bool) -> CellValue:
    """A timestamp with an explicit offset, stored as UTC so text order is time order."""
    if not isinstance(value, str):
        raise CellProblem("Expected a timestamp such as 2026-01-31T09:30:00Z")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise CellProblem("Expected an ISO 8601 timestamp with a time zone") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CellProblem("The timestamp needs a time zone, such as Z or +02:00")
    try:
        return parsed.astimezone(UTC).isoformat(timespec="microseconds")
    except OverflowError:
        # An offset can push a timestamp near year 1 or 9999 out of the range UTC has.
        raise CellProblem("Timestamp is out of range") from None


def _option_id(value: object, column: ColumnDef, writing: bool) -> str:
    if not isinstance(value, str):
        raise CellProblem("Expected the id of one of the column's options")
    try:
        option_id = UUID(value)
    except ValueError:
        raise CellProblem("Expected the id of one of the column's options") from None
    for option in column.options:
        if option.id == option_id:
            if writing and option.archived:
                raise CellProblem("That option is archived and can no longer be chosen")
            return str(option_id)
    raise CellProblem("That is not one of the column's options")


def _single_select(value: object, column: ColumnDef, writing: bool) -> CellValue:
    return _option_id(value, column, writing)


def _multi_select(value: object, column: ColumnDef, writing: bool) -> CellValue:
    if not isinstance(value, list):
        raise CellProblem("Expected a list of option ids")
    chosen = [_option_id(item, column, writing) for item in value]
    if len(set(chosen)) != len(chosen):
        raise CellProblem("The same option is listed twice")
    return chosen


COLUMN_TYPES: dict[ColumnTypeName, ColumnType] = {
    column_type.name: column_type
    for column_type in (
        ColumnType("text", SqlKind.TEXT, _TEXTUAL, True, _text_of(MAX_TEXT)),
        ColumnType("long_text", SqlKind.TEXT, _TEXTUAL, True, _text_of(MAX_LONG_TEXT)),
        ColumnType("number", SqlKind.NUMERIC, _ORDERED, True, _number),
        ColumnType("integer", SqlKind.INTEGER, _ORDERED, True, _integer),
        ColumnType("boolean", SqlKind.BOOLEAN, _EQUALITY, True, _boolean),
        ColumnType("date", SqlKind.DATE, _ORDERED, True, _date),
        ColumnType("datetime", SqlKind.DATETIME, _ORDERED, True, _datetime),
        ColumnType(
            "single_select",
            SqlKind.TEXT,
            frozenset({"eq", "ne", "in", "is_null"}),
            True,
            _single_select,
        ),
        ColumnType(
            "multi_select",
            SqlKind.ARRAY,
            frozenset({"contains", "is_null"}),
            False,
            _multi_select,
        ),
    )
}

OPTION_TYPES: frozenset[ColumnTypeName] = frozenset({"single_select", "multi_select"})


def validate_cell(column: ColumnDef, value: object) -> CellValue:
    """The value as it will be stored, or :class:`CellProblem`. `None` clears the cell."""
    if value is None:
        if not column.nullable:
            raise CellProblem("This column cannot be empty")
        return None
    return COLUMN_TYPES[column.type].validate(value, column, True)


def validate_default(column: ColumnDef) -> CellValue:
    """A column's default, held to the same rule as any other cell."""
    if column.default is None:
        return None
    return COLUMN_TYPES[column.type].validate(column.default, column, True)


def validate_filter(column: ColumnDef, op: FilterOp, value: FilterValue) -> FilterValue:
    """A filter's operand, or :class:`CellProblem` when the operator does not suit the column."""
    column_type = COLUMN_TYPES[column.type]
    if op not in column_type.filter_ops:
        allowed = ", ".join(sorted(column_type.filter_ops))
        raise CellProblem(f"A {column.type} column supports these operators: {allowed}")
    if op == "is_null":
        if not isinstance(value, bool):
            raise CellProblem("is_null takes true or false")
        return value
    if op == "in":
        if not isinstance(value, list) or not 0 < len(value) <= MAX_IN_OPERANDS:
            raise CellProblem(f"in takes a list of 1 to {MAX_IN_OPERANDS} values")
        operands: list[CellValue] = [column_type.validate(item, column, False) for item in value]
        return operands
    if op == "contains" and column_type.kind is SqlKind.ARRAY:
        return _option_id(value, column, False)
    if value is None:
        raise CellProblem(f"{op} needs a value; use is_null to test for an empty cell")
    return column_type.validate(value, column, False)
