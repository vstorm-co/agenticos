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
    MAX_OPTIONS,
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
    """Live columns that now demand a value and that existing records may lack one for."""


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
    if len(options) > MAX_OPTIONS:
        # A left-out option is archived, never dropped, so without a ceiling on the merged list
        # each change could add up to MAX_OPTIONS more, every version would carry them all, and
        # a `TableRead` could no longer be sent back as a `SchemaUpdate`.
        raise InvalidSchemaError(
            field, f"A column holds at most {MAX_OPTIONS} options, archived ones included"
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
        # Stored in its normalized form, exactly as a cell would be: a default of
        # 3.0 on an integer column would otherwise put JSONB 3.0 in every record,
        # and the bigint cast a sort or filter makes on it would fail.
        column = column.model_copy(update={"default": validate_default(column)})
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


def _becomes_required(old: ColumnDef, new: ColumnDef) -> bool:
    """Whether a live required column is one records may now lack a value for.

    Two ways in: an optional column that becomes required, and a required column that comes
    back from the archive. Records written while it was archived could not hold a value for
    it, so un-archiving without a default leaves every one of them missing something the
    column now demands. With a default the next edit fills it, exactly as for a new column.
    """
    return old.nullable or (old.archived and new.default is None)


def diff(previous: Sequence[ColumnDef], current: Sequence[ColumnDef]) -> SchemaDiff:
    """Which existing columns a change archives, and which it makes required or restores as required."""
    before = {column.id: column for column in previous}
    archived = frozenset(
        column.id
        for column in current
        if column.archived and column.id in before and not before[column.id].archived
    )
    required = frozenset(
        column.id
        for column in current
        if not column.nullable
        and not column.archived
        and column.id in before
        and _becomes_required(before[column.id], column)
    )
    return SchemaDiff(archived=archived, required=required)
