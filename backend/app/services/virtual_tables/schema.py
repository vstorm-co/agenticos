"""Turning a submitted column list into the next schema version.

A schema change is submitted as the columns the table should have. This module
reconciles that list with the columns the table has now, and it is where the
rules that keep stored records meaningful live:

- a column keeps its id for life, so an existing column is matched by id and
  never by label; renaming one changes no record;
- a column's type changes only to one its values read as (`conversions`), and
  the change rewrites them; any other would leave values meaning nothing;
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
from app.services.virtual_tables.conversions import CONVERSIONS, convertible
from app.services.virtual_tables.exceptions import InvalidSchemaError
from app.services.virtual_tables.formula import FormulaProblem, check_formula, rename_references
from app.services.virtual_tables.types import (
    COMPUTED_TYPES,
    OPTION_TYPES,
    READ_THROUGH_LINK,
    CellProblem,
    validate_default,
)


@dataclass(frozen=True)
class SchemaDiff:
    """What a change does to the columns that already existed."""

    archived: frozenset[UUID]
    """Columns that were live and are now archived."""

    required: frozenset[UUID]
    """Live columns that now demand a value and that existing records may lack one for."""

    retyped: frozenset[UUID]
    """Columns whose type changed, whose values every record must be rewritten for."""


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
    if (
        previous is not None
        and previous.type != submitted.type
        and not convertible(previous.type, submitted.type)
    ):
        into = ", ".join(sorted(CONVERSIONS[previous.type]))
        raise InvalidSchemaError(
            f"{where}.type",
            f"A {previous.type} column cannot become {submitted.type}; it can become {into}. "
            "Add a new column instead",
        )
    if submitted.options and submitted.type not in OPTION_TYPES:
        raise InvalidSchemaError(f"{where}.options", f"A {submitted.type} column has no options")
    _check_reference(where, submitted, previous)
    # Options carry over from one kind of choice to the other; a column that stops
    # being a choice has none, and one that becomes one starts from what was sent.
    keeps_options = (
        previous is not None and previous.type in OPTION_TYPES and submitted.type in OPTION_TYPES
    )
    options = _options(
        f"{where}.options", submitted.options, previous.options if keeps_options else []
    )
    column = ColumnDef(
        id=previous.id if previous else uuid4(),
        label=submitted.label,
        type=submitted.type,
        nullable=submitted.nullable,
        default=submitted.default,
        options=options,
        archived=submitted.archived,
        link_table_id=submitted.link_table_id,
        link_column_id=submitted.link_column_id,
        target_column_id=submitted.target_column_id,
        aggregate=submitted.aggregate,
        formula=submitted.formula,
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


def _check_reference(where: str, submitted: ColumnInput, previous: ColumnDef | None) -> None:
    """What a link, lookup or rollup column must name - and what no other column may.

    Whether the named table and columns exist, and whether the caller may read
    them, is the service's to ask: it takes the database (`TableOperations`).
    """
    kind = submitted.type
    if (submitted.link_table_id is not None) != (kind == "link"):
        raise InvalidSchemaError(
            f"{where}.link_table_id",
            "A link column names the table it links to, and only a link column does",
        )
    if (
        previous is not None
        and previous.type == "link"
        and previous.link_table_id != submitted.link_table_id
    ):
        # Its values are ids of that table's records; in another table they name nothing.
        raise InvalidSchemaError(
            f"{where}.link_table_id",
            "A link column keeps the table it links to. Add a new link column instead",
        )
    reads = kind in READ_THROUGH_LINK
    if (submitted.link_column_id is not None) != reads:
        raise InvalidSchemaError(
            f"{where}.link_column_id",
            "A lookup or rollup column names the link column it reads through, and only those do",
        )
    if (submitted.aggregate is not None) != (kind == "rollup"):
        raise InvalidSchemaError(
            f"{where}.aggregate", "A rollup column says what it works out, and only a rollup does"
        )
    counts = kind == "rollup" and submitted.aggregate == "count"
    if (submitted.target_column_id is not None) != (reads and not counts):
        raise InvalidSchemaError(
            f"{where}.target_column_id",
            "A lookup, or a rollup that is not a count, names the linked table's column it reads",
        )
    if kind in COMPUTED_TYPES and (not submitted.nullable or submitted.default is not None):
        raise InvalidSchemaError(
            f"{where}.nullable", "A worked-out column has no default and cannot be required"
        )
    if kind == "link" and submitted.default is not None:
        raise InvalidSchemaError(f"{where}.default", "A link column has no default")
    if (submitted.formula is not None) != (kind == "formula"):
        raise InvalidSchemaError(
            f"{where}.formula", "A formula column holds a formula, and only a formula column does"
        )


def _check_formulas(columns: list[ColumnDef], previous: Sequence[ColumnDef]) -> list[ColumnDef]:
    """`columns` with every formula reading renamed columns by their new labels, each
    checked: it parses, and names live columns of the table that hold values."""
    old = {column.id: column.label for column in previous}
    renamed = {
        old[column.id]: column.label
        for column in columns
        if column.id in old and old[column.id] != column.label
    }
    checked: list[ColumnDef] = []
    for index, column in enumerate(columns):
        if column.type == "formula" and column.formula is not None:
            column = column.model_copy(
                update={"formula": rename_references(column.formula, renamed)}
            )
            if not column.archived:
                try:
                    check_formula(column.formula or "", column, columns)
                except FormulaProblem as problem:
                    raise InvalidSchemaError(f"columns.{index}.formula", str(problem)) from None
        checked.append(column)
    return checked


def _check_links(columns: Sequence[ColumnDef]) -> None:
    """Every live lookup and rollup reads through a live link column of the same table."""
    links = {column.id for column in columns if column.type == "link" and not column.archived}
    for index, column in enumerate(columns):
        if column.archived or column.type not in READ_THROUGH_LINK:
            continue
        if column.link_column_id not in links:
            raise InvalidSchemaError(
                f"columns.{index}.link_column_id",
                "That is not a live link column of this table. Save the link column first, "
                "or archive the lookups and rollups that read it",
            )


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
    _check_links(columns)
    return _check_formulas(columns, previous)


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
    retyped = frozenset(
        column.id
        for column in current
        if column.id in before and before[column.id].type != column.type
    )
    return SchemaDiff(archived=archived, required=required, retyped=retyped)
