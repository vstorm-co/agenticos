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
from urllib.parse import urlsplit
from uuid import UUID

from app.repositories.virtual_table import SqlKind
from app.schemas.virtual_table import CellValue, ColumnDef, ColumnTypeName, FilterOp, FilterValue

MAX_TEXT = 1_000
MAX_LONG_TEXT = 100_000
MAX_INTEGER = 2**53 - 1
"""The largest integer a JavaScript client can hold exactly, which the API shares with them."""

MAX_IN_OPERANDS = 100
MAX_EMAIL = 254
"""The longest address SMTP carries (RFC 5321's path limit)."""
MAX_URL = 2_048
MAX_RATING = 5
MAX_LINKS = 100
"""Records one link cell names: a link is a reference, not a way to hold a list."""

# Deliberately loose: one `@`, a dot in the domain, no spaces. Whether a mailbox
# exists is not a cell's question, and a stricter pattern refuses real addresses.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PHONE = re.compile(r"\+?[0-9 ().\-/]+")
_MIN_PHONE_DIGITS = 5
_MAX_PHONE = 32

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
    computed: bool = False
    """Read from other values when a record is read, never stored, written,
    filtered or sorted by - see `computed.py`."""


def _text_of(limit: int) -> Validator:
    def validate(value: object, column: ColumnDef, writing: bool) -> CellValue:
        if not isinstance(value, str):
            raise CellProblem("Expected text")
        if "\x00" in value:
            raise CellProblem("Text cannot contain a NUL character")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            # A lone surrogate: accepted by the JSON parser, refused by PostgreSQL.
            raise CellProblem("Text cannot contain characters that are not valid Unicode") from None
        if len(value) > limit:
            raise CellProblem(f"Text is longer than {limit} characters")
        return value

    return validate


def _email(value: object, column: ColumnDef, writing: bool) -> CellValue:
    text = str(_text_of(MAX_EMAIL)(value, column, writing))
    if not _EMAIL.fullmatch(text):
        raise CellProblem("Expected an email address such as ada@example.com")
    return text


def _url(value: object, column: ColumnDef, writing: bool) -> CellValue:
    text = str(_text_of(MAX_URL)(value, column, writing))
    parsed = urlsplit(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or " " in text:
        raise CellProblem("Expected a web address starting with http:// or https://")
    return text


def _phone(value: object, column: ColumnDef, writing: bool) -> CellValue:
    text = str(_text_of(_MAX_PHONE)(value, column, writing))
    if not _PHONE.fullmatch(text):
        raise CellProblem("Expected a phone number of digits, spaces and + ( ) - .")
    if sum(character.isdigit() for character in text) < _MIN_PHONE_DIGITS:
        raise CellProblem(f"A phone number has at least {_MIN_PHONE_DIGITS} digits")
    return text


def _rating(value: object, column: ColumnDef, writing: bool) -> CellValue:
    rating = _integer(value, column, writing)
    if not isinstance(rating, int) or not 1 <= rating <= MAX_RATING:
        raise CellProblem(f"Expected a rating from 1 to {MAX_RATING}")
    return rating


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


def _not_an_option(column: ColumnDef) -> CellProblem:
    """The refusal of a value that names no option, saying which ones there are."""
    live = ", ".join(option.label for option in column.options if not option.archived)
    return CellProblem(f"That is not one of the column's options: {live or 'none'}")


def _option_id(value: object, column: ColumnDef, writing: bool) -> str:
    if not isinstance(value, str):
        raise _not_an_option(column)
    try:
        option_id = UUID(value)
    except ValueError:
        raise _not_an_option(column) from None
    for option in column.options:
        if option.id == option_id:
            if writing and option.archived:
                raise CellProblem("That option is archived and can no longer be chosen")
            return str(option_id)
    raise _not_an_option(column)


def _record_id(value: object) -> str:
    if not isinstance(value, str):
        raise CellProblem("Expected a record id")
    try:
        return str(UUID(value))
    except ValueError:
        raise CellProblem("Expected a record id") from None


def _link(value: object, column: ColumnDef, writing: bool) -> CellValue:
    """Record ids of the linked table. Whether each exists is the service's question."""
    if not isinstance(value, list):
        raise CellProblem("Expected a list of record ids")
    if len(value) > MAX_LINKS:
        raise CellProblem(f"A cell links at most {MAX_LINKS} records")
    linked = [_record_id(item) for item in value]
    if len(set(linked)) != len(linked):
        raise CellProblem("The same record is linked twice")
    return linked


def _computed(value: object, column: ColumnDef, writing: bool) -> CellValue:
    raise CellProblem("This column is worked out from others and cannot be written")


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
        ColumnType("email", SqlKind.TEXT, _TEXTUAL, True, _email),
        ColumnType("url", SqlKind.TEXT, _TEXTUAL, True, _url),
        ColumnType("phone", SqlKind.TEXT, _TEXTUAL, True, _phone),
        ColumnType("number", SqlKind.NUMERIC, _ORDERED, True, _number),
        ColumnType("integer", SqlKind.INTEGER, _ORDERED, True, _integer),
        ColumnType("rating", SqlKind.INTEGER, _ORDERED, True, _rating),
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
        ColumnType("link", SqlKind.ARRAY, frozenset({"contains", "is_null"}), False, _link),
        ColumnType("lookup", SqlKind.TEXT, frozenset(), False, _computed, computed=True),
        ColumnType("rollup", SqlKind.TEXT, frozenset(), False, _computed, computed=True),
    )
}

OPTION_TYPES: frozenset[ColumnTypeName] = frozenset({"single_select", "multi_select"})
COMPUTED_TYPES: frozenset[ColumnTypeName] = frozenset(
    name for name, column_type in COLUMN_TYPES.items() if column_type.computed
)
READ_THROUGH_LINK: frozenset[ColumnTypeName] = frozenset({"lookup", "rollup"})
"""The computed types that read the records a link column of the same table names."""
SEARCHED_TYPES: frozenset[ColumnTypeName] = frozenset(
    {"text", "long_text", "email", "url", "phone"}
)
"""The types a table's search box reads as text."""


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
    if column_type.computed:
        raise CellProblem("A worked-out column cannot be filtered on; filter the column it reads")
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
    if op == "contains" and column.type == "link":
        return _record_id(value)
    if op == "contains" and column_type.kind is SqlKind.ARRAY:
        return _option_id(value, column, False)
    if op in ("contains", "starts_with"):
        # A piece of a value, not a whole one: `@example` finds addresses at a
        # domain without being an address itself.
        return _text_of(MAX_TEXT)(value, column, False)
    if value is None:
        raise CellProblem(f"{op} needs a value; use is_null to test for an empty cell")
    return column_type.validate(value, column, False)
