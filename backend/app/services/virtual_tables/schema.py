"""Turning a submitted column list into the next schema version.

A schema change is submitted as the columns the table should have. This module
reconciles that list with the columns the table has now, and it is where the
rules that keep stored records meaningful live:

- a column keeps its id for life, so an existing column is matched by id and
  never by label; renaming one changes no record;
- a column's type never changes, because the values stored under it would no
  longer mean what they did;
- nothing is deleted. A column or select option left out of the submission is
  archived: its values stay readable and it can no longer be written;
- a new required column needs a default, since the records that already exist
  hold nothing for it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.schemas.virtual_table import (
    MAX_COLUMNS,
    ColumnDef,
    ColumnInput,
    OptionDef,
    OptionInput,
)
from app.services.virtual_tables.exceptions import InvalidSchemaError
from app.services.virtual_tables.types import OPTION_TYPES, CellProblem, validate_default


@dataclass(frozen=True)
class SchemaDiff:
    """What a change does to the columns that already existed."""

    archived: frozenset[UUID]
    """Columns that were live and are now archived."""

    required: frozenset[UUID]
    """Columns that allowed an empty cell and now do not."""


def _options(
    field: str, submitted: Sequence[OptionInput], previous: Sequence[OptionDef]
) -> list[OptionDef]:
    known = {option.id: option for option in previous}
    seen: set[UUID] = set()
    options: list[OptionDef] = []
    for index, option in enumerate(submitted):
        where = f"{field}.{index}"
        if option.id is not None:
            if option.id not in known:
                raise InvalidSchemaError(f"{where}.id", "That option does not exist on this column")
            if option.id in seen:
                raise InvalidSchemaError(f"{where}.id", "This option is listed twice")
            seen.add(option.id)
        options.append(
            OptionDef(id=option.id or uuid4(), label=option.label, archived=option.archived)
        )
    options.extend(
        OptionDef(id=old.id, label=old.label, archived=True)
        for old in previous
        if old.id not in seen
    )
    labels = [option.label for option in options if not option.archived]
    if len(set(labels)) != len(labels):
        raise InvalidSchemaError(field, "Two live options have the same label")
    return options


def _column(index: int, submitted: ColumnInput, previous: ColumnDef | None) -> ColumnDef:
    where = f"columns.{index}"
    if previous is not None and previous.type != submitted.type:
        raise InvalidSchemaError(
            f"{where}.type",
            f"A column's type cannot be changed (it is {previous.type}); add a new column instead",
        )
    if submitted.options and submitted.type not in OPTION_TYPES:
        raise InvalidSchemaError(f"{where}.options", f"A {submitted.type} column has no options")
    options = _options(f"{where}.options", submitted.options, previous.options if previous else [])
    column = ColumnDef(
        id=previous.id if previous else uuid4(),
        label=submitted.label,
        type=submitted.type,
        nullable=submitted.nullable,
        default=submitted.default,
        options=options,
        archived=submitted.archived,
    )
    try:
        validate_default(column)
    except CellProblem as problem:
        raise InvalidSchemaError(f"{where}.default", str(problem)) from None
    if previous is None and not column.nullable and column.default is None:
        raise InvalidSchemaError(
            f"{where}.default",
            "A new required column needs a default, because existing records hold nothing for it",
        )
    return column


def build_columns(
    submitted: Sequence[ColumnInput], previous: Sequence[ColumnDef]
) -> list[ColumnDef]:
    """The full column list of the next version, or :class:`InvalidSchemaError`.

    Columns come out in the order submitted, followed by the previous columns that
    were left out, now archived.
    """
    known = {column.id: column for column in previous}
    seen: set[UUID] = set()
    columns: list[ColumnDef] = []
    for index, item in enumerate(submitted):
        if item.id is not None:
            if item.id not in known:
                raise InvalidSchemaError(f"columns.{index}.id", "That column does not exist")
            if item.id in seen:
                raise InvalidSchemaError(f"columns.{index}.id", "This column is listed twice")
            seen.add(item.id)
        columns.append(_column(index, item, known.get(item.id) if item.id else None))
    columns.extend(
        old.model_copy(update={"archived": True}) for old in previous if old.id not in seen
    )
    if len(columns) > MAX_COLUMNS:
        raise InvalidSchemaError(
            "columns", f"A table holds at most {MAX_COLUMNS} columns, archived ones included"
        )
    labels = [column.label for column in columns if not column.archived]
    if len(set(labels)) != len(labels):
        raise InvalidSchemaError("columns", "Two live columns have the same label")
    return columns


def diff(previous: Sequence[ColumnDef], current: Sequence[ColumnDef]) -> SchemaDiff:
    """Which existing columns a change archives, and which it makes required."""
    before = {column.id: column for column in previous}
    archived = frozenset(
        column.id
        for column in current
        if column.archived and column.id in before and not before[column.id].archived
    )
    required = frozenset(
        column.id
        for column in current
        if not column.nullable and column.id in before and before[column.id].nullable
    )
    return SchemaDiff(archived=archived, required=required)
