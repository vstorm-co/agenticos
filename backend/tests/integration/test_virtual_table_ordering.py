"""Ordering by time across separate transactions, where each write has its own clock."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

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
