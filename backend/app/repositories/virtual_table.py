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

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    ColumnElement,
    Date,
    DateTime,
    Numeric,
    and_,
    cast,
    false,
    func,
    or_,
    select,
    text,
)
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
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[VirtualTable], int]:
    """The tables one member may see, by name, with the unpaged total.

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
    items = await db.execute(
        select(VirtualTable)
        .where(*where)
        .order_by(VirtualTable.name.asc(), VirtualTable.id.asc())
        .offset(skip)
        .limit(limit)
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
) -> VirtualTableRecord | None:
    """Insert a record at revision 1, or `None` if that external id is already taken.

    The conflict target is the partial unique index on `(table_id, external_id)`,
    so two concurrent inserts of one external id cannot both succeed: the second
    waits for the first to commit, then finds the row and returns nothing.
    """
    statement = (
        pg_insert(VirtualTableRecord)
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
            # Both from the same `now()`, so a record nobody has edited sorts by when it
            # was created rather than falling behind every edited one as a NULL would.
            created_at=func.now(),
            updated_at=func.now(),
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
) -> VirtualTableRecord:
    """Write new values and advance the revision. The caller holds the row lock."""
    record.values = values
    record.schema_version = schema_version
    record.revision = record.revision + 1
    record.updated_by = updated_by
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


async def list_records(
    db: AsyncSession,
    *,
    table_id: UUID,
    organization_id: UUID,
    filters: list[FilterClause],
    sort: SortClause,
    skip: int,
    limit: int,
) -> list[VirtualTableRecord]:
    """A page of records. The order is total: the record id always breaks a tie.

    Records with no value in the sorted column come last in either direction.
    """
    if sort.column_id is not None:
        key = _typed(sort.column_id, sort.kind)
    elif sort.field == "updated_at":
        key = VirtualTableRecord.updated_at
    else:
        key = VirtualTableRecord.created_at
    ordered = key.desc().nulls_last() if sort.direction == "desc" else key.asc().nulls_last()
    query = (
        select(VirtualTableRecord)
        .where(
            and_(
                VirtualTableRecord.table_id == table_id,
                VirtualTableRecord.organization_id == organization_id,
                *[_predicate(clause) for clause in filters],
            )
        )
        .order_by(ordered, VirtualTableRecord.id.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


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
    )
    db.add(row)
    await db.flush()
    return row


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
