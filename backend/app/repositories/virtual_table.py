"""Virtual Tables repository (PostgreSQL async).

Pure data access. Every function that touches a table or its records takes the
`organization_id` and filters on it, so a table id from another tenant finds
nothing here rather than relying on a caller to check afterwards.

Records live in one JSONB document keyed by column id, so a typed comparison
reads the cell as text and casts it (:func:`_typed`). The service has already
validated every stored value against its column's type, which is what makes the
cast safe; nothing here re-checks it.

Two writes are built on `INSERT ... ON CONFLICT DO NOTHING ... RETURNING` rather
than "read, then insert", because that is what makes them race-free:
:func:`insert_record` (a second insert of one external id returns nothing instead
of a duplicate) and :func:`claim_receipt` (a retried operation key claims the same
row). A caller that loses the race gets `None` and reads the winner.
"""

from collections.abc import AsyncGenerator, Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, NamedTuple
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    ColumnElement,
    Date,
    DateTime,
    Numeric,
    Text,
    and_,
    any_,
    cast,
    delete,
    false,
    func,
    literal,
    literal_column,
    or_,
    select,
    text,
    tuple_,
    union_all,
    update,
)
from sqlalchemy import column as sa_column
from sqlalchemy import values as sa_values
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, array
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.resource_grant import Visibility
from app.db.models.virtual_table import (
    VirtualTable,
    VirtualTableOutbox,
    VirtualTableReceipt,
    VirtualTableRecord,
    VirtualTableRecordHistory,
    VirtualTableSchemaVersion,
)
from app.repositories._search import contains_ci
from app.schemas.virtual_table import CellValue, FilterOp, FilterValue, SortDirection


async def storage_bytes(db: AsyncSession, *, organization_id: UUID) -> int:
    """Stored JSONB payload bytes, including retained copies, scoped to one tenant.

    pg_column_size reads TOAST sizes without decompressing the complete values.
    Callers serialize checks and writes with the organization's storage lock.
    """
    totals = union_all(
        select(
            func.coalesce(func.sum(func.pg_column_size(VirtualTableRecord.values)), 0).label(
                "bytes"
            )
        ).where(VirtualTableRecord.organization_id == organization_id),
        select(
            func.coalesce(
                func.sum(
                    func.coalesce(func.pg_column_size(VirtualTableRecordHistory.before), 0)
                    + func.coalesce(func.pg_column_size(VirtualTableRecordHistory.after), 0)
                ),
                0,
            ).label("bytes")
        ).where(VirtualTableRecordHistory.organization_id == organization_id),
        select(
            func.coalesce(func.sum(func.pg_column_size(VirtualTableReceipt.outcome)), 0).label(
                "bytes"
            )
        ).where(VirtualTableReceipt.organization_id == organization_id),
        select(
            func.coalesce(func.sum(func.pg_column_size(VirtualTableOutbox.payload)), 0).label(
                "bytes"
            )
        ).where(VirtualTableOutbox.organization_id == organization_id),
    ).subquery()
    held = await db.scalar(select(func.sum(totals.c.bytes)))
    return int(held or 0)


class SqlKind(StrEnum):
    """How a cell is read out of the JSONB document to compare or sort it."""

    TEXT = "text"
    NUMERIC = "numeric"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    ARRAY = "array"


@dataclass(frozen=True)
class FilterClause:
    """One validated condition on one column."""

    column_id: UUID
    kind: SqlKind
    op: FilterOp
    value: FilterValue


@dataclass(frozen=True)
class SearchClause:
    """Text a record must contain somewhere a person would read it.

    `text_columns` are the live text and long text columns, searched for `term`
    itself. A select cell holds option ids, not what anyone typed, so it is
    searched through `options`: for each live select column, the ids of the
    options whose label contains the term, and whether the column holds many.
    """

    term: str
    text_columns: tuple[UUID, ...]
    options: tuple[tuple[UUID, bool, tuple[str, ...]], ...]


@dataclass(frozen=True)
class SortClause:
    """What a listing is ordered by, ahead of the record id that always breaks ties.

    `column_id` is set for a column and `None` for a record timestamp, in which
    case `field` names which one.
    """

    direction: SortDirection
    column_id: UUID | None = None
    kind: SqlKind = SqlKind.TEXT
    field: str = "created_at"


# -- tables ------------------------------------------------------------------


async def get_table(
    db: AsyncSession,
    table_id: UUID,
    *,
    organization_id: UUID,
    for_update: bool = False,
    for_share: bool = False,
) -> VirtualTable | None:
    """One table in one organization.

    `for_update` serializes schema changes and archiving. `for_share` is what a record
    write takes: any number of writers hold it together, and it conflicts with
    `for_update`, so a write and a schema change or archive of the same table never
    interleave. Both re-read the row once they get the lock, so a waiter sees the
    committed schema version and archive state rather than the ones it started with.
    """
    query = select(VirtualTable).where(
        VirtualTable.id == table_id, VirtualTable.organization_id == organization_id
    )
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    elif for_share:
        query = query.with_for_update(read=True).execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_live_table_by_name(
    db: AsyncSession, name: str, *, organization_id: UUID
) -> VirtualTable | None:
    result = await db.execute(
        select(VirtualTable).where(
            VirtualTable.name == name,
            VirtualTable.organization_id == organization_id,
            VirtualTable.archived_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_tables_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    include_archived: bool = False,
    search: str | None = None,
    sort: Literal["name", "updated_at"] = "name",
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[VirtualTable], int]:
    """The tables one member may see, by name or by most recently changed, with the unpaged total.

    `see_all` is true when the caller's role reaches the whole organization; the
    ownership predicate is then skipped. Otherwise a member sees their own, the
    org-visible ones and those explicitly shared with them (`shared_ids`).
    """
    where = [VirtualTable.organization_id == organization_id]
    if not include_archived:
        where.append(VirtualTable.archived_at.is_(None))
    if not see_all:
        where.append(
            or_(
                VirtualTable.owner_user_id == user_id,
                VirtualTable.visibility == Visibility.ORG.value,
                VirtualTable.id.in_(shared_ids) if shared_ids else false(),
            )
        )
    if search:
        where.append(
            or_(
                contains_ci(VirtualTable.name, search),
                contains_ci(VirtualTable.description, search),
            )
        )
    if sort == "updated_at":
        # `updated_at` is set only by `onupdate`, so a table never touched since
        # creation has it `NULL` - falling back to `created_at` is what keeps
        # such a table ranked by when it actually last changed, rather than
        # sorting before or after every table that has an `updated_at` at all.
        order_by = (
            func.coalesce(VirtualTable.updated_at, VirtualTable.created_at).desc(),
            VirtualTable.id.asc(),
        )
    else:
        order_by = (VirtualTable.name.asc(), VirtualTable.id.asc())
    items = await db.execute(
        select(VirtualTable).where(*where).order_by(*order_by).offset(skip).limit(limit)
    )
    total = await db.scalar(select(func.count(VirtualTable.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def create_table(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
    name: str,
    description: str | None,
    visibility: str,
) -> VirtualTable:
    table = VirtualTable(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        name=name,
        description=description,
        visibility=visibility,
        schema_version=1,
    )
    db.add(table)
    await db.flush()
    await db.refresh(table)
    return table


async def update_table(
    db: AsyncSession, *, table: VirtualTable, update_data: dict[str, Any]
) -> VirtualTable:
    for field, value in update_data.items():
        setattr(table, field, value)
    await db.flush()
    await db.refresh(table)
    return table


async def add_schema_version(
    db: AsyncSession,
    *,
    table_id: UUID,
    version: int,
    columns: list[dict[str, Any]],
    created_by: UUID | None,
) -> VirtualTableSchemaVersion:
    row = VirtualTableSchemaVersion(
        table_id=table_id, version=version, columns=columns, created_by=created_by
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_schema_version(
    db: AsyncSession, *, table_id: UUID, version: int
) -> VirtualTableSchemaVersion:
    """One version of a table's schema.

    Every table row names a version that was written in the same transaction, so a
    missing one is a broken invariant, not a request to refuse: it raises.
    """
    result = await db.execute(
        select(VirtualTableSchemaVersion).where(
            VirtualTableSchemaVersion.table_id == table_id,
            VirtualTableSchemaVersion.version == version,
        )
    )
    return result.scalar_one()


async def list_schema_versions(
    db: AsyncSession, *, table_id: UUID
) -> list[VirtualTableSchemaVersion]:
    result = await db.execute(
        select(VirtualTableSchemaVersion)
        .where(VirtualTableSchemaVersion.table_id == table_id)
        .order_by(VirtualTableSchemaVersion.version.asc())
    )
    return list(result.scalars().all())


async def count_tables(db: AsyncSession, *, organization_id: UUID) -> int:
    """Every table the organization has, archived ones included.

    Archived ones count because nothing deletes a table: its records and history stay,
    so it goes on costing what it cost.
    """
    count = await db.scalar(
        select(func.count(VirtualTable.id)).where(VirtualTable.organization_id == organization_id)
    )
    return count or 0


async def count_records_up_to(
    db: AsyncSession, *, table_id: UUID, organization_id: UUID, ceiling: int
) -> int:
    """How many records the table holds, counting no further than `ceiling`.

    Bounded so a create against a table at its limit reads `ceiling` index entries
    and not the whole table, which is all the answer "is there room" needs.
    """
    capped = (
        select(VirtualTableRecord.id)
        .where(
            VirtualTableRecord.table_id == table_id,
            VirtualTableRecord.organization_id == organization_id,
        )
        .limit(ceiling)
        .subquery()
    )
    count = await db.scalar(select(func.count()).select_from(capped))
    return count or 0


async def record_counts(
    db: AsyncSession, *, organization_id: UUID, table_ids: Sequence[UUID]
) -> dict[UUID, int]:
    """How many records each table holds, for a page of tables in one grouped query.

    A table with none is absent from the answer.
    """
    if not table_ids:
        return {}
    rows = await db.execute(
        select(VirtualTableRecord.table_id, func.count(VirtualTableRecord.id))
        .where(
            VirtualTableRecord.organization_id == organization_id,
            VirtualTableRecord.table_id.in_(table_ids),
        )
        .group_by(VirtualTableRecord.table_id)
    )
    return dict(rows.all())


async def current_columns(
    db: AsyncSession, *, tables: Sequence[VirtualTable]
) -> dict[UUID, list[dict[str, Any]]]:
    """Each table's current schema columns, for a page of tables in one query."""
    if not tables:
        return {}
    rows = await db.execute(
        select(VirtualTableSchemaVersion.table_id, VirtualTableSchemaVersion.columns).where(
            tuple_(VirtualTableSchemaVersion.table_id, VirtualTableSchemaVersion.version).in_(
                [(table.id, table.schema_version) for table in tables]
            )
        )
    )
    return dict(rows.all())


async def column_values(
    db: AsyncSession, *, table_id: UUID, column_id: UUID
) -> list[tuple[UUID, Any]]:
    """Every record's value for one column, by record id - those that hold one."""
    key = str(column_id)
    rows = await db.execute(
        select(VirtualTableRecord.id, VirtualTableRecord.values[key]).where(
            VirtualTableRecord.table_id == table_id, VirtualTableRecord.values.has_key(key)
        )
    )
    return [(record_id, value) for record_id, value in rows.all()]


_REWRITE_BATCH = 1_000
"""Records rewritten per statement: one round trip each, not one per record."""


async def rewrite_column(
    db: AsyncSession,
    *,
    table_id: UUID,
    column_id: UUID,
    values: Sequence[tuple[UUID, Any]],
) -> None:
    """Set one column's value on each record named, bumping its revision.

    A value of None takes the key out, as an empty cell is stored. The bumped
    revision makes an edit made against the old value a conflict, not a write of a
    value its column no longer accepts.
    """
    key = str(column_id)
    kept = [(record_id, value) for record_id, value in values if value is not None]
    cleared = [record_id for record_id, value in values if value is None]
    for start in range(0, len(kept), _REWRITE_BATCH):
        cells = sa_values(
            sa_column("rid", PG_UUID(as_uuid=True)), sa_column("cell", JSONB), name="cells"
        ).data(kept[start : start + _REWRITE_BATCH])
        await db.execute(
            update(VirtualTableRecord)
            .where(VirtualTableRecord.table_id == table_id, VirtualTableRecord.id == cells.c.rid)
            .values(
                values=func.jsonb_set(VirtualTableRecord.values, [key], cells.c.cell),
                revision=VirtualTableRecord.revision + 1,
            )
            .execution_options(synchronize_session=False)
        )
    for start in range(0, len(cleared), _REWRITE_BATCH):
        await db.execute(
            update(VirtualTableRecord)
            .where(
                VirtualTableRecord.table_id == table_id,
                VirtualTableRecord.id.in_(cleared[start : start + _REWRITE_BATCH]),
            )
            .values(
                values=VirtualTableRecord.values.op("-")(key),
                revision=VirtualTableRecord.revision + 1,
            )
            .execution_options(synchronize_session=False)
        )


async def count_records_without_value(db: AsyncSession, *, table_id: UUID, column_id: UUID) -> int:
    """How many records hold nothing for a column - what stops it becoming required."""
    count = await db.scalar(
        select(func.count(VirtualTableRecord.id)).where(
            VirtualTableRecord.table_id == table_id,
            ~VirtualTableRecord.values.has_key(str(column_id)),
        )
    )
    return count or 0


# -- records -----------------------------------------------------------------


async def get_record(
    db: AsyncSession,
    record_id: UUID,
    *,
    table_id: UUID,
    organization_id: UUID,
    for_update: bool = False,
) -> VirtualTableRecord | None:
    query = select(VirtualTableRecord).where(
        VirtualTableRecord.id == record_id,
        VirtualTableRecord.table_id == table_id,
        VirtualTableRecord.organization_id == organization_id,
    )
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_records_by_ids(
    db: AsyncSession, record_ids: Collection[UUID], *, table_id: UUID, organization_id: UUID
) -> list[VirtualTableRecord]:
    """The records of one table among `record_ids`; an id it does not hold is left out."""
    found: list[VirtualTableRecord] = []
    ids = list(record_ids)
    for start in range(0, len(ids), _REWRITE_BATCH):
        result = await db.execute(
            select(VirtualTableRecord).where(
                VirtualTableRecord.id.in_(ids[start : start + _REWRITE_BATCH]),
                VirtualTableRecord.table_id == table_id,
                VirtualTableRecord.organization_id == organization_id,
            )
        )
        found.extend(result.scalars())
    return found


async def get_record_by_external_id(
    db: AsyncSession,
    external_id: str,
    *,
    table_id: UUID,
    organization_id: UUID,
    for_update: bool = False,
) -> VirtualTableRecord | None:
    query = select(VirtualTableRecord).where(
        VirtualTableRecord.external_id == external_id,
        VirtualTableRecord.table_id == table_id,
        VirtualTableRecord.organization_id == organization_id,
    )
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def record_exists(
    db: AsyncSession, external_id: str, *, table_id: UUID, organization_id: UUID
) -> bool:
    found = await db.scalar(
        select(VirtualTableRecord.id).where(
            VirtualTableRecord.external_id == external_id,
            VirtualTableRecord.table_id == table_id,
            VirtualTableRecord.organization_id == organization_id,
        )
    )
    return found is not None


async def insert_record(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    external_id: str | None,
    schema_version: int,
    values: dict[str, CellValue],
    created_by: UUID | None,
    source: dict[str, str | int | bool | None] | None = None,
) -> VirtualTableRecord | None:
    """Insert a record at revision 1, or `None` if that external id is already taken.

    The conflict target is the partial unique index on `(table_id, external_id)`,
    so two concurrent inserts of one external id cannot both succeed: the second
    waits for the first to commit, then finds the row and returns nothing.
    """
    # The clock, not `now()`: that is when the transaction began, so every record
    # a batch, an imported file or a workflow's loop wrote got one instant and the
    # id tiebreak shuffled them out of the order they were written in. Read once,
    # in a CTE - a volatile one is evaluated once however often it is referenced.
    clock = select(func.clock_timestamp().label("at")).cte("written_at")
    written_at = select(clock.c.at).scalar_subquery()
    statement = (
        pg_insert(VirtualTableRecord)
        .add_cte(clock)
        .values(
            id=uuid4(),
            organization_id=organization_id,
            table_id=table_id,
            external_id=external_id,
            schema_version=schema_version,
            values=values,
            revision=1,
            created_by=created_by,
            updated_by=created_by,
            created_source=source,
            updated_source=source,
            # One stamp for both, so a record nobody has edited sorts by when it was
            # created rather than falling behind every edited one as a NULL would.
            created_at=written_at,
            updated_at=written_at,
        )
        .on_conflict_do_nothing(
            index_elements=["table_id", "external_id"],
            index_where=text("external_id IS NOT NULL"),
        )
        .returning(VirtualTableRecord)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def update_record(
    db: AsyncSession,
    *,
    record: VirtualTableRecord,
    values: dict[str, CellValue],
    schema_version: int,
    updated_by: UUID | None,
    source: dict[str, str | int | bool | None] | None = None,
) -> VirtualTableRecord:
    """Write new values and advance the revision. The caller holds the row lock."""
    record.values = values
    record.schema_version = schema_version
    record.revision = record.revision + 1
    record.updated_by = updated_by
    record.updated_source = source
    await db.flush()
    await db.refresh(record)
    return record


async def delete_record(db: AsyncSession, record: VirtualTableRecord) -> None:
    await db.delete(record)
    await db.flush()


def _cell(column_id: UUID) -> ColumnElement[Any]:
    return VirtualTableRecord.values[str(column_id)]


def _typed(column_id: UUID, kind: SqlKind) -> ColumnElement[Any]:
    """A cell as a typed SQL value, for comparing and sorting."""
    raw = _cell(column_id).astext
    match kind:
        case SqlKind.NUMERIC:
            return cast(raw, Numeric)
        case SqlKind.INTEGER:
            return cast(raw, BigInteger)
        case SqlKind.BOOLEAN:
            return cast(raw, Boolean)
        case SqlKind.DATE:
            return cast(raw, Date)
        case SqlKind.DATETIME:
            return cast(raw, DateTime(timezone=True))
        case _:
            return raw


def _operand(kind: SqlKind, value: object) -> object:
    """A validated operand as the Python type the driver binds for this SQL type."""
    match kind:
        case SqlKind.NUMERIC:
            return Decimal(str(value))
        case SqlKind.DATE:
            return date.fromisoformat(str(value))
        case SqlKind.DATETIME:
            return datetime.fromisoformat(str(value))
        case _:
            return value


def _predicate(clause: FilterClause) -> ColumnElement[bool]:
    column_id = clause.column_id
    if clause.op == "is_null":
        present = VirtualTableRecord.values.has_key(str(column_id))
        return ~present if clause.value else present
    if clause.kind is SqlKind.ARRAY:
        return _cell(column_id).contains([clause.value])
    cell = _typed(column_id, clause.kind)
    if clause.op == "in":
        values = clause.value if isinstance(clause.value, list) else []
        return cell.in_([_operand(clause.kind, item) for item in values])
    if clause.op == "contains":
        return contains_ci(cell, str(clause.value))
    if clause.op == "starts_with":
        return cell.startswith(str(clause.value), autoescape=True)
    operand = _operand(clause.kind, clause.value)
    match clause.op:
        case "eq":
            return cell == operand
        case "ne":
            return cell != operand
        case "lt":
            return cell < operand
        case "lte":
            return cell <= operand
        case "gt":
            return cell > operand
        case _:
            return cell >= operand


def _search_predicate(search: SearchClause) -> ColumnElement[bool]:
    matches = [
        contains_ci(_cell(column_id).astext, search.term) for column_id in search.text_columns
    ]
    for column_id, many, option_ids in search.options:
        if many:
            matches.append(_cell(column_id).has_any(array(option_ids)))
        else:
            matches.append(_cell(column_id).astext.in_(option_ids))
    # Nothing searchable, or no option labelled that way: a search nothing can meet.
    return or_(*matches) if matches else false()


def _matching(
    table_id: UUID,
    organization_id: UUID,
    filters: list[FilterClause],
    search: SearchClause | None,
) -> ColumnElement[bool]:
    """The records of one table a listing or a count reads: its tenant's, meeting every clause."""
    return and_(
        VirtualTableRecord.table_id == table_id,
        VirtualTableRecord.organization_id == organization_id,
        *[_predicate(clause) for clause in filters],
        *([] if search is None else [_search_predicate(search)]),
    )


async def count_records(
    db: AsyncSession,
    *,
    table_id: UUID,
    organization_id: UUID,
    filters: list[FilterClause],
    search: SearchClause | None,
    cap: int,
) -> int:
    """How many records match, counting no further than `cap + 1`.

    Counting stops there so a count of a huge table costs a bounded scan: the
    caller learns the exact number up to the cap, and that there are more past it.
    """
    matching = (
        select(VirtualTableRecord.id)
        .where(_matching(table_id, organization_id, filters, search))
        .limit(cap + 1)
        .subquery()
    )
    return (await db.execute(select(func.count()).select_from(matching))).scalar_one()


def _order(sort: SortClause) -> tuple[ColumnElement[Any], ...]:
    """The total order of a listing: the sort, then the record id that breaks every tie.

    Records with no value in the sorted column come last in either direction. A
    `created_at` sort breaks its ties on the id in its own direction, and every
    other sort on the id ascending.
    """
    desc = sort.direction == "desc"
    record_id = VirtualTableRecord.id
    if sort.column_id is None and sort.field != "updated_at":
        # The default listing, and the one an index serves:
        # `virtual_table_records_table_created_idx` is `(table_id, created_at, id)`,
        # read forwards or backwards. That takes no `NULLS LAST` - a no-op on a NOT
        # NULL column, but one the planner does not see through - and a tiebreak
        # running the same way as the key: `created_at DESC, id ASC` is an order no
        # scan of the index produces, so "latest first" sorted every matching
        # record to return one page.
        created = VirtualTableRecord.created_at
        return (created.desc(), record_id.desc()) if desc else (created.asc(), record_id.asc())
    key = (
        VirtualTableRecord.updated_at
        if sort.column_id is None
        else _typed(sort.column_id, sort.kind)
    )
    return (key.desc().nulls_last() if desc else key.asc().nulls_last(), record_id.asc())


async def list_records(
    db: AsyncSession,
    *,
    table_id: UUID,
    organization_id: UUID,
    filters: list[FilterClause],
    sort: SortClause,
    skip: int,
    limit: int,
    search: SearchClause | None = None,
) -> list[VirtualTableRecord]:
    """A page of records, in the total order of :func:`_order`."""
    query = (
        select(VirtualTableRecord)
        .where(_matching(table_id, organization_id, filters, search))
        .order_by(*_order(sort))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def stream_export_records(
    db: AsyncSession,
    *,
    table_id: UUID,
    organization_id: UUID,
    filters: list[FilterClause],
    sort: SortClause,
    search: SearchClause | None,
    max_records: int,
    batch_records: int,
    batch_bytes: int,
) -> AsyncGenerator[list[VirtualTableRecord]]:
    """Read one ordered snapshot, with bounded driver prefetch and output batches.

    Four records per cursor fetch bound raw prefetch at four times the record
    byte ceiling. Sizes are measured before TOAST compression. Avoid OFFSET:
    small byte-bounded pages must not re-scan and re-size preceding rows.
    """
    result = await db.stream(
        select(
            VirtualTableRecord,
            (func.octet_length(cast(VirtualTableRecord.values, Text)) + 256).label("bytes"),
        )
        .where(_matching(table_id, organization_id, filters, search))
        .order_by(*_order(sort))
        .limit(max_records)
        .execution_options(yield_per=4)
    )
    batch: list[VirtualTableRecord] = []
    size = 0
    try:
        async for record, record_bytes in result:
            if batch and (len(batch) >= batch_records or size + record_bytes > batch_bytes):
                yield batch
                batch = []
                size = 0
            batch.append(record)
            size += record_bytes
        if batch:
            yield batch
    finally:
        await result.close()


class RecordCells(NamedTuple):
    """A record with only some of its cells: a `RecordRead`'s fields, `values` projected.

    `RecordRead.model_validate(cells)` reads it as it reads a row.
    """

    id: UUID
    table_id: UUID
    external_id: str | None
    schema_version: int
    revision: int
    created_at: datetime
    updated_at: datetime | None
    created_by: UUID | None
    updated_by: UUID | None
    values: dict[str, Any]


def _projected(keys: Sequence[str]) -> ColumnElement[dict[str, Any]]:
    """A record's `values` with only the cells under `keys`, built in the database.

    A scalar subquery over `jsonb_each` rather than `jsonb_build_object`, which
    takes at most 100 arguments. Typed `JSONB` so the driver hands back a mapping.
    """
    cells = func.jsonb_each(VirtualTableRecord.values).table_valued("key", "value").alias("cells")
    return (
        select(
            func.coalesce(
                func.jsonb_object_agg(cells.c.key, cells.c.value),
                literal_column("'{}'::jsonb"),
                type_=JSONB,
            )
        )
        .select_from(cells)
        .where(cells.c.key == any_(literal(list(keys), type_=ARRAY(Text))))
        .correlate(VirtualTableRecord)
        .scalar_subquery()
    )


def _size(keys: Sequence[str]) -> ColumnElement[int]:
    """How many bytes the projected cells take as JSON text."""
    return func.octet_length(cast(_projected(keys), Text))


def _among(
    record_ids: Collection[UUID], table_id: UUID, organization_id: UUID
) -> ColumnElement[bool]:
    """The records of one table, in its tenant, among `record_ids`: one array parameter
    however many ids there are, so the read is one statement."""
    return and_(
        VirtualTableRecord.id
        == any_(literal(list(record_ids), type_=ARRAY(PG_UUID(as_uuid=True)))),
        VirtualTableRecord.table_id == table_id,
        VirtualTableRecord.organization_id == organization_id,
    )


async def list_record_sizes(
    db: AsyncSession,
    *,
    table_id: UUID,
    organization_id: UUID,
    filters: list[FilterClause],
    search: SearchClause | None,
    sort: SortClause,
    limit: int,
    keys: Sequence[str],
) -> list[tuple[UUID, int]]:
    """The first `limit` matching records' ids, in :func:`list_records`' order, each with
    the size of its cells under `keys`. No cell crosses the wire, only its size."""
    result = await db.execute(
        select(VirtualTableRecord.id, _size(keys))
        .where(_matching(table_id, organization_id, filters, search))
        .order_by(*_order(sort))
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_record_sizes_by_ids(
    db: AsyncSession,
    record_ids: Collection[UUID],
    *,
    table_id: UUID,
    organization_id: UUID,
    keys: Sequence[str],
) -> dict[UUID, int]:
    """The size of each record's cells under `keys`; an id the table does not hold is left out."""
    result = await db.execute(
        select(VirtualTableRecord.id, _size(keys)).where(
            _among(record_ids, table_id, organization_id)
        )
    )
    return {row[0]: row[1] for row in result.all()}


async def get_record_cells_by_ids(
    db: AsyncSession,
    record_ids: Collection[UUID],
    *,
    table_id: UUID,
    organization_id: UUID,
    keys: Sequence[str],
) -> list[RecordCells]:
    """The records among `record_ids` with only their cells under `keys`, in no set order.

    An id the table does not hold is left out.
    """
    record = VirtualTableRecord
    result = await db.execute(
        select(
            record.id,
            record.table_id,
            record.external_id,
            record.schema_version,
            record.revision,
            record.created_at,
            record.updated_at,
            record.created_by,
            record.updated_by,
            _projected(keys),
        ).where(_among(record_ids, table_id, organization_id))
    )
    return [RecordCells(*row) for row in result.all()]


async def set_statement_timeout(db: AsyncSession, *, ms: int) -> None:
    """Limit each later statement of this transaction to `ms` milliseconds (`SET LOCAL`).

    `ms` must be at least 1: Postgres reads `0` as no limit.
    """
    await db.execute(text("SELECT set_config('statement_timeout', :ms, true)"), {"ms": str(ms)})


async def statement_timeout(db: AsyncSession) -> str:
    """This transaction's `statement_timeout`, as Postgres reports it: `0`, `2s`, `150ms`."""
    result = await db.execute(text("SELECT current_setting('statement_timeout')"))
    return str(result.scalar_one())


async def restore_statement_timeout(db: AsyncSession, *, setting: str) -> None:
    """Put back a `statement_timeout` read by `statement_timeout`, for the rest of the transaction."""
    await db.execute(
        text("SELECT set_config('statement_timeout', :setting, true)"), {"setting": setting}
    )


# -- history, outbox, receipts -----------------------------------------------


async def add_history(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    record_id: UUID,
    revision: int,
    operation: str,
    actor_user_id: UUID | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> VirtualTableRecordHistory:
    row = VirtualTableRecordHistory(
        organization_id=organization_id,
        table_id=table_id,
        record_id=record_id,
        revision=revision,
        operation=operation,
        actor_user_id=actor_user_id,
        before=before,
        after=after,
    )
    db.add(row)
    await db.flush()
    return row


async def add_outbox(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    record_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> VirtualTableOutbox:
    row = VirtualTableOutbox(
        organization_id=organization_id,
        table_id=table_id,
        record_id=record_id,
        event_type=event_type,
        payload=payload,
        # When the row is written, not when its transaction began (`now()`): a
        # write that waited on a trigger's activation lock has to land after it.
        created_at=func.clock_timestamp(),
    )
    db.add(row)
    await db.flush()
    return row


async def delete_expired_receipt(
    db: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    operation: str,
    operation_key: str,
    cutoff: datetime,
) -> None:
    """Remove this exact key's receipt if it was created before `cutoff`.

    A receipt past its lifetime must not answer a retry, whether or not the retention
    sweep has reached it yet, so a claim clears its own key's expired receipt first and
    then claims as if there had never been one. Only this key's row: the sweep is what
    reclaims the rest.
    """
    await db.execute(
        delete(VirtualTableReceipt).where(
            VirtualTableReceipt.organization_id == organization_id,
            VirtualTableReceipt.principal_id == principal_id,
            VirtualTableReceipt.operation == operation,
            VirtualTableReceipt.operation_key == operation_key,
            VirtualTableReceipt.created_at < cutoff,
        )
    )


async def claim_receipt(
    db: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    operation: str,
    operation_key: str,
    payload_hash: str,
) -> VirtualTableReceipt | None:
    """Claim an operation key, or `None` if this principal already used it for this operation.

    A concurrent claim of the same key waits for the first transaction to end.
    If that one committed the claim finds the row and returns nothing; if it
    rolled back the claim succeeds, because nothing was written.
    """
    statement = (
        pg_insert(VirtualTableReceipt)
        .values(
            id=uuid4(),
            organization_id=organization_id,
            principal_id=principal_id,
            operation=operation,
            operation_key=operation_key,
            payload_hash=payload_hash,
            outcome={},
        )
        .on_conflict_do_nothing(constraint="uq_virtual_table_receipt_key")
        .returning(VirtualTableReceipt)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def read_receipt(
    db: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    operation: str,
    operation_key: str,
) -> VirtualTableReceipt:
    """The receipt a failed :func:`claim_receipt` collided with. It exists, so this raises if not."""
    result = await db.execute(
        select(VirtualTableReceipt).where(
            VirtualTableReceipt.organization_id == organization_id,
            VirtualTableReceipt.principal_id == principal_id,
            VirtualTableReceipt.operation == operation,
            VirtualTableReceipt.operation_key == operation_key,
        )
    )
    return result.scalar_one()


async def set_receipt_outcome(
    db: AsyncSession, *, receipt: VirtualTableReceipt, outcome: dict[str, Any]
) -> None:
    receipt.outcome = outcome
    await db.flush()
