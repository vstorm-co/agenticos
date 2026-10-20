"""Ordering by time across separate transactions, where each write has its own clock."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.virtual_table import VirtualTableRecord
from app.schemas.virtual_table import (
    ColumnInput,
    RecordCreate,
    RecordQuery,
    RecordSort,
    RecordUpdate,
    TableCreate,
)
from app.services.virtual_tables import VirtualTableService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


async def _table_with_three_committed_records(engine: AsyncEngine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        owner = await make_user(setup)
        org = await make_org(setup, owner=owner)
        ctx = ctx_for(owner, org)
        table = await VirtualTableService(setup).create_table(
            ctx,
            TableCreate(name="Orders", columns=[ColumnInput(label="Note", type="text")]),
        )
        await setup.commit()
    ids = []
    for external_id in ("first", "second", "third"):
        async with factory() as session:
            written = await VirtualTableService(session).create_record(
                ctx, table.id, RecordCreate(external_id=external_id, values={})
            )
            await session.commit()
            ids.append(written.record)
    return factory, ctx, table, ids


async def _listed(factory, ctx, table, sort):
    async with factory() as session:
        page = await VirtualTableService(session).list_records(
            ctx, table.id, RecordQuery(sort=sort)
        )
    return [item.external_id for item in page.items]


async def test_a_new_record_is_as_updated_as_it_is_created(engine: AsyncEngine):
    _factory, _ctx, _table, records = await _table_with_three_committed_records(engine)

    assert all(record.updated_at == record.created_at for record in records)


async def test_sorting_by_updated_at_puts_the_newest_create_first_when_nothing_was_edited(
    engine: AsyncEngine,
):
    factory, ctx, table, _records = await _table_with_three_committed_records(engine)

    newest_first = await _listed(factory, ctx, table, RecordSort(by="updated_at", direction="desc"))
    oldest_first = await _listed(factory, ctx, table, RecordSort(by="updated_at", direction="asc"))

    assert newest_first == ["third", "second", "first"]
    assert oldest_first == ["first", "second", "third"]


async def test_an_edited_record_moves_to_the_front_of_updated_at_desc(engine: AsyncEngine):
    factory, ctx, table, records = await _table_with_three_committed_records(engine)
    async with factory() as session:
        await VirtualTableService(session).update_record(
            ctx,
            table.id,
            records[0].id,
            RecordUpdate(expected_revision=1, values={str(table.columns[0].id): "edited"}),
        )
        await session.commit()

    order = await _listed(factory, ctx, table, RecordSort(by="updated_at", direction="desc"))

    assert order == ["first", "third", "second"]


@pytest.mark.parametrize("direction", ["asc", "desc"])
async def test_records_tied_on_the_sort_field_come_out_in_id_order_in_either_direction(
    engine: AsyncEngine, direction
):
    """A column sort breaks every tie on the record id, ascending, whichever way it runs.

    A `created_at` sort is the exception: it breaks its ties on the id in its own direction
    (`test_latest_first_breaks_a_creation_tie_on_the_id_newest_first_too`). Record ids are
    random, so the order the records were written in - the order a listing without the
    tiebreak would most likely hand back - is not their id order, and a missing tiebreak
    shows.
    """
    factory, ctx, table, _records = await _table_with_three_committed_records(engine)
    note = str(table.columns[0].id)
    for n in range(10):
        async with factory() as session:
            await VirtualTableService(session).create_record(
                ctx, table.id, RecordCreate(external_id=f"tie{n}", values={note: "same"})
            )
            await session.commit()

    async with factory() as session:
        page = await VirtualTableService(session).list_records(
            ctx, table.id, RecordQuery(sort=RecordSort(by=note, direction=direction), limit=100)
        )

    tied = [item.id for item in page.items if item.values.get(note) == "same"]
    assert len(tied) == 10
    assert tied == sorted(tied)


async def _table_with_records_created_at_once(db: AsyncSession, count: int):
    """`count` records sharing one `created_at`, so only the id can order them.

    Set by hand: each write stamps its own clock, so even records written in one
    transaction do not reliably tie.
    """
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    service = VirtualTableService(db)
    table = await service.create_table(
        ctx, TableCreate(name="Orders", columns=[ColumnInput(label="Note", type="text")])
    )
    for n in range(count):
        await service.create_record(ctx, table.id, RecordCreate(external_id=f"r{n}", values={}))
    await db.execute(
        update(VirtualTableRecord)
        .where(VirtualTableRecord.table_id == table.id)
        .values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    )
    return service, ctx, table


async def test_latest_first_breaks_a_creation_tie_on_the_id_newest_first_too(db):
    """A `created_at` listing breaks its ties on the id in its own direction - the order
    its index holds - and paging through it still meets every record exactly once."""
    service, ctx, table = await _table_with_records_created_at_once(db, 7)

    for direction in ("asc", "desc"):
        sort = RecordSort(by="created_at", direction=direction)
        listed = await service.list_records(ctx, table.id, RecordQuery(sort=sort, limit=100))
        keys = [(item.created_at, item.id) for item in listed.items]
        assert len({created for created, _ in keys}) == 1, "the records must tie"
        assert keys == sorted(keys, reverse=direction == "desc")

        paged = []
        for skip in (0, 3, 6):
            page = await service.list_records(
                ctx, table.id, RecordQuery(sort=sort, skip=skip, limit=3)
            )
            paged.extend(item.id for item in page.items)
        assert paged == [item.id for item in listed.items]


@pytest.mark.parametrize("direction", ["asc", "desc"])
async def test_a_listing_by_creation_time_is_read_off_its_index_without_sorting(db, direction):
    """`created_at DESC NULLS LAST, id ASC` is an order no scan of
    `(table_id, created_at, id)` produces, so "latest first" sorted every matching
    record to return a page. The plan for the listing's own statement must be the
    index read in order - backwards for `desc` - with no Sort above it.

    Sequential scans are switched off for the plan: on a table this small the planner
    would rightly prefer one, and what is asked is whether the index *can* serve it.
    """
    service, ctx, table = await _table_with_records_created_at_once(db, 3)
    captured: list[tuple[str, Any]] = []

    def capture(_conn, _cursor, statement, parameters, _context, _executemany) -> None:
        if "FROM virtual_table_records" in statement and "ORDER BY" in statement:
            captured.append((statement, parameters))

    sync_engine = db.get_bind()
    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        await service.list_records(
            ctx, table.id, RecordQuery(sort=RecordSort(by="created_at", direction=direction))
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)

    [(statement, parameters)] = captured
    connection = await db.connection()
    await connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
    plan = "\n".join(
        row[0] for row in await connection.exec_driver_sql(f"EXPLAIN {statement}", parameters)
    )

    assert "virtual_table_records_table_created_idx" in plan
    assert ("Backward" in plan) is (direction == "desc")
    assert "Sort" not in plan
