"""What a record does not store: whom its links name, and the columns worked out from others.

A link column stores the ids of another table's records. A record is read with
each link's records named (`RecordRead.links`), and with every lookup and rollup
column worked out from the linked records' values - at read time, for the page
being read, in one query per linked table rather than one per record. Nothing
here is written: a lookup is always what the linked records say now.

Reading through a link goes no further than the reader may. A linked table the
reader cannot see leaves its links unnamed and every column read through them
empty, rather than showing a private table's values to someone outside it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import CellValue, ColumnDef, LinkedRecord, RecordRead
from app.services.access import TABLE, resolve_access
from app.services.virtual_tables.formula import references, work_out
from app.services.virtual_tables.types import READ_THROUGH_LINK

_NAMED_BY = ("text", "email", "url", "phone", "long_text")
"""The types a linked record is named by, its first live column of one of them."""
MAX_LABEL = 200


@dataclass(frozen=True)
class Reach:
    """What reading some columns of a table takes: the columns behind them and the linked tables."""

    columns: frozenset[UUID]
    """The columns named, and every column one of them is worked out from."""
    linked: Mapping[UUID, frozenset[UUID]]
    """Each linked table read, and the columns read there. A link alone reads none:
    its records' names come from the linked table's naming column, chosen at read time."""


def reach(columns: Sequence[ColumnDef], named: Iterable[UUID]) -> Reach:
    """Every column and linked table that reading `named` from a table of `columns` takes.

    Pure: nothing is read. A formula takes the live columns its labels name, matched
    exactly as `check_formula` matches them; a lookup or rollup takes its link column
    and, unless it counts the links, its target column in the linked table; a link
    takes its linked table. A formula may not name a formula or a link, so the walk
    goes no deeper than formula, then lookup or rollup, then link.
    """
    by_id = {column.id: column for column in columns}
    live_labels = {column.label: column.id for column in columns if not column.archived}
    reached: set[UUID] = set()
    linked: dict[UUID, set[UUID]] = {}
    pending = list(named)
    while pending:
        column_id = pending.pop()
        if column_id in reached:
            continue
        reached.add(column_id)
        column = by_id.get(column_id)
        if column is None:
            continue
        if column.type == "formula":
            labels = references(column.formula or "")
            pending.extend(live_labels[label] for label in labels if label in live_labels)
        elif column.type in READ_THROUGH_LINK and column.link_column_id is not None:
            pending.append(column.link_column_id)
            link = by_id.get(column.link_column_id)
            if link is not None and link.link_table_id is not None:
                targets = linked.setdefault(link.link_table_id, set())
                if column.aggregate != "count" and column.target_column_id is not None:
                    targets.add(column.target_column_id)
        elif column.type == "link" and column.link_table_id is not None:
            linked.setdefault(column.link_table_id, set())
    return Reach(
        columns=frozenset(reached),
        linked={table_id: frozenset(targets) for table_id, targets in linked.items()},
    )


@dataclass(frozen=True)
class _Linked:
    """One linked table as far as the reader may see it: its columns and the records named."""

    columns: list[ColumnDef]
    values: dict[str, dict[str, CellValue]]
    names: dict[str, str]


async def _linked_table(
    db: AsyncSession, ctx: AuthContext, table_id: UUID, ids: set[str]
) -> _Linked | None:
    """The records of `table_id` among `ids`, or `None` when the reader may not see the table."""
    table = await virtual_table_repo.get_table(db, table_id, organization_id=ctx.organization_id)
    if table is None or not await resolve_access(
        db, ctx, table, Perm.TABLES_VIEW, resource_type=TABLE
    ):
        return None
    version = await virtual_table_repo.get_schema_version(
        db, table_id=table.id, version=table.schema_version
    )
    columns = [ColumnDef.model_validate(column) for column in version.columns]
    rows = await virtual_table_repo.get_records_by_ids(
        db,
        [UUID(record_id) for record_id in ids],
        table_id=table.id,
        organization_id=ctx.organization_id,
    )
    named_by = next((c for c in columns if not c.archived and c.type in _NAMED_BY), None)
    values: dict[str, dict[str, CellValue]] = {}
    names: dict[str, str] = {}
    for row in rows:
        record_id = str(row.id)
        values[record_id] = dict(row.values)
        names[record_id] = _name(values[record_id], named_by) or row.external_id or record_id[:8]
    return _Linked(columns=columns, values=values, names=names)


def _name(values: dict[str, CellValue], column: ColumnDef | None) -> str | None:
    if column is None:
        return None
    value = values.get(str(column.id))
    return value[:MAX_LABEL] if isinstance(value, str) and value.strip() else None


def _readable(value: CellValue, column: ColumnDef) -> list[CellValue]:
    """A linked cell as a lookup shows it: a choice by its label, several as several."""
    labels = {str(option.id): option.label for option in column.options}
    if isinstance(value, list):
        return [labels.get(item, item) for item in value]
    if isinstance(value, str) and column.options:
        return [labels.get(value, value)]
    return [value]


def _work_out(
    column: ColumnDef, ids: Sequence[str], linked: _Linked
) -> CellValue | list[CellValue]:
    """A lookup's or rollup's value for one record's links, or `None` for nothing to show."""
    present = [record_id for record_id in ids if record_id in linked.values]
    if column.aggregate == "count":
        return len(present)
    target = next((c for c in linked.columns if c.id == column.target_column_id), None)
    if target is None or target.archived:
        return None
    read = [
        item
        for record_id in present
        if (value := linked.values[record_id].get(str(target.id))) is not None
        for item in _readable(value, target)
    ]
    if column.type == "lookup":
        return read or None
    numbers = [
        item for item in read if isinstance(item, int | float) and not isinstance(item, bool)
    ]
    if column.aggregate == "sum":
        return sum(numbers) if numbers else None
    if column.aggregate == "avg":
        return sum(numbers) / len(numbers) if numbers else None
    if numbers:
        return min(numbers) if column.aggregate == "min" else max(numbers)
    # Dates and timestamps are stored ISO 8601, UTC, so text order is time order.
    dates = [item for item in read if isinstance(item, str)]
    if not dates:
        return None
    return min(dates) if column.aggregate == "min" else max(dates)


async def read_through(
    db: AsyncSession, ctx: AuthContext, columns: Sequence[ColumnDef], records: list[RecordRead]
) -> list[RecordRead]:
    """`records` with each link's records named, and every lookup, rollup and formula
    worked out - formulas last, since one may read what a rollup worked out."""
    records = await _with_links(db, ctx, columns, records)
    formulas = [
        column
        for column in columns
        if column.type == "formula" and not column.archived and column.formula is not None
    ]
    if not formulas:
        return records
    return [
        record.model_copy(update={"values": _with_formulas(record.values, formulas, columns)})
        for record in records
    ]


def _with_formulas(
    values: dict[str, Any], formulas: Sequence[ColumnDef], columns: Sequence[ColumnDef]
) -> dict[str, Any]:
    worked_out = dict(values)
    for column in formulas:
        result = work_out(column.formula or "", columns, values)
        if result is None:
            worked_out.pop(str(column.id), None)
        else:
            worked_out[str(column.id)] = result
    return worked_out


async def _with_links(
    db: AsyncSession, ctx: AuthContext, columns: Sequence[ColumnDef], records: list[RecordRead]
) -> list[RecordRead]:
    """`records` with each link's records named and every lookup and rollup worked out."""
    link_tables = {
        column.id: column.link_table_id
        for column in columns
        if column.type == "link" and not column.archived and column.link_table_id is not None
    }
    if not link_tables or not records:
        return records
    wanted: dict[UUID, set[str]] = {}
    for column_id, table_id in link_tables.items():
        ids = wanted.setdefault(table_id, set())
        for record in records:
            ids.update(record.values.get(str(column_id)) or [])
    tables = {
        table_id: await _linked_table(db, ctx, table_id, ids) for table_id, ids in wanted.items()
    }
    reading = [
        column
        for column in columns
        if column.type in READ_THROUGH_LINK
        and not column.archived
        and column.link_column_id in link_tables
    ]
    result: list[RecordRead] = []
    for record in records:
        values = dict(record.values)
        named: dict[str, list[LinkedRecord]] = {}
        for column_id, table_id in link_tables.items():
            linked = tables[table_id]
            if linked is None:
                continue
            named[str(column_id)] = [
                LinkedRecord(id=UUID(record_id), label=linked.names[record_id])
                for record_id in record.values.get(str(column_id)) or []
                if record_id in linked.names
            ]
        for column in reading:
            link_id = column.link_column_id
            linked = tables[link_tables[link_id]] if link_id is not None else None
            worked_out = (
                None
                if linked is None or link_id is None
                else _work_out(column, record.values.get(str(link_id)) or [], linked)
            )
            if worked_out is None:
                values.pop(str(column.id), None)
            else:
                values[str(column.id)] = worked_out
        result.append(record.model_copy(update={"values": values, "links": named}))
    return result
