"""A record write and a schema change or archive of the same table never interleave.

Both interleavings are built by holding one transaction open and starting the other
against it, which is deterministic where a `gather` is only likely. The write takes
a share lock on the table row and a schema change or archive takes an update lock,
so the second transaction waits for the first to commit and then acts on what it
committed. Without the lock the waiter would not wait: it would read the old state,
and the record would land in an archived table, or a column would become required
while an uncommitted record without a value sat beside it.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.virtual_table import VirtualTableRecord
from app.schemas.virtual_table import (
    RecordCreate,
    RecordUpdate,
    RecordUpsert,
    SchemaUpdate,
    TableCreate,
    TableUpdate,
)
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables.exceptions import InvalidSchemaError, TableArchivedError
from tests.integration.virtual_table_support import column, ctx_for, make_org, make_user

pytestmark = [pytest.mark.anyio, pytest.mark.security]

# Long enough for a blocked statement to have started waiting, short enough to keep the
# suite quick. The assertion that the waiter is still pending is what proves it blocked.
_SETTLE = 0.4


async def _committed_table(engine: AsyncEngine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        owner = await make_user(setup)
        org = await make_org(setup, owner=owner)
        ctx = ctx_for(owner, org)
        table = await VirtualTableService(setup).create_table(
            ctx, TableCreate(name="People", columns=[column("Name", "text")])
        )
        await setup.commit()
    return factory, ctx, table


async def _own_session(factory, work):
    async with factory() as session:
        try:
            result = await work(VirtualTableService(session))
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


async def test_a_write_waits_for_an_archive_in_flight_and_is_then_refused(engine: AsyncEngine):
    factory, ctx, table = await _committed_table(engine)

    async with factory() as archiving:
        await VirtualTableService(archiving).archive_table(ctx, table.id)
        write = asyncio.create_task(
            _own_session(
                factory,
                lambda service: service.create_record(ctx, table.id, RecordCreate(values={})),
            )
        )
        await asyncio.sleep(_SETTLE)
        assert not write.done(), "the write did not wait for the archive"
        await archiving.commit()

    with pytest.raises(TableArchivedError):
        await write
    async with factory() as check:
        assert await check.scalar(select(func.count()).select_from(VirtualTableRecord)) == 0


async def test_an_archive_waits_for_a_write_in_flight(engine: AsyncEngine):
    factory, ctx, table = await _committed_table(engine)

    async with factory() as writing:
        await VirtualTableService(writing).create_record(ctx, table.id, RecordCreate(values={}))
        archive = asyncio.create_task(
            _own_session(factory, lambda service: service.archive_table(ctx, table.id))
        )
        await asyncio.sleep(_SETTLE)
        assert not archive.done(), "the archive did not wait for the write"
        await writing.commit()

    assert (await archive).archived_at is not None
    async with factory() as check:
        assert await check.scalar(select(func.count()).select_from(VirtualTableRecord)) == 1


async def test_a_column_cannot_become_required_beside_an_uncommitted_record_without_a_value(
    engine: AsyncEngine,
):
    factory, ctx, table = await _committed_table(engine)
    name = table.columns[0].id

    async with factory() as writing:
        await VirtualTableService(writing).create_record(ctx, table.id, RecordCreate(values={}))
        tighten = asyncio.create_task(
            _own_session(
                factory,
                lambda service: service.update_schema(
                    ctx,
                    table.id,
                    SchemaUpdate(
                        expected_version=1,
                        columns=[column("Name", "text", id=name, nullable=False)],
                    ),
                ),
            )
        )
        await asyncio.sleep(_SETTLE)
        assert not tighten.done(), "the schema change did not wait for the write"
        await writing.commit()

    with pytest.raises(InvalidSchemaError, match="no value"):
        await tighten
    async with factory() as check:
        assert (await VirtualTableService(check).describe_table(ctx, table.id)).schema_version == 1


async def _write_waits_for_archive(engine: AsyncEngine, write):
    """Hold an archive open, start `write` against it, and check it waits then is refused.

    `write` is `(service, ctx, table, record) -> awaitable`. The record exists and is
    committed before the archive starts, so each call has a real row to act on. Updating
    or deleting a row touches nothing the archive's row lock would block, so only the
    write's own share lock on the table can make it wait.
    """
    factory, ctx, table = await _committed_table(engine)
    record = await _own_session(
        factory,
        lambda service: service.create_record(
            ctx, table.id, RecordCreate(external_id="A-1", values={})
        ),
    )

    async with factory() as archiving:
        await VirtualTableService(archiving).archive_table(ctx, table.id)
        attempt = asyncio.create_task(
            _own_session(factory, lambda service: write(service, ctx, table, record.record))
        )
        await asyncio.sleep(_SETTLE)
        assert not attempt.done(), "the write did not wait for the archive"
        await archiving.commit()

    with pytest.raises(TableArchivedError):
        await attempt
    async with factory() as check:
        stored = await check.scalar(select(VirtualTableRecord.revision))
        assert stored == 1, "the refused write changed or removed the record"


async def test_an_update_waits_for_an_archive_in_flight_and_is_then_refused(engine: AsyncEngine):
    await _write_waits_for_archive(
        engine,
        lambda service, ctx, table, record: service.update_record(
            ctx, table.id, record.id, RecordUpdate(expected_revision=1, values={})
        ),
    )


async def test_an_upsert_of_an_existing_record_waits_for_an_archive_in_flight(engine: AsyncEngine):
    await _write_waits_for_archive(
        engine,
        lambda service, ctx, table, record: service.upsert_record(
            ctx, table.id, "A-1", RecordUpsert(values={}, expected_revision=1)
        ),
    )


async def test_an_upsert_that_creates_waits_for_an_archive_in_flight(engine: AsyncEngine):
    await _write_waits_for_archive(
        engine,
        lambda service, ctx, table, record: service.upsert_record(
            ctx, table.id, "B-2", RecordUpsert(values={})
        ),
    )


async def test_a_delete_waits_for_an_archive_in_flight_and_is_then_refused(engine: AsyncEngine):
    await _write_waits_for_archive(
        engine,
        lambda service, ctx, table, record: service.delete_record(
            ctx, table.id, record.id, expected_revision=1
        ),
    )


async def test_a_rename_waits_for_an_archive_in_flight_and_is_then_refused(engine: AsyncEngine):
    """Without a lock the rename read the live row, passed the archive check and renamed it."""
    factory, ctx, table = await _committed_table(engine)

    async with factory() as archiving:
        await VirtualTableService(archiving).archive_table(ctx, table.id)
        rename = asyncio.create_task(
            _own_session(
                factory,
                lambda service: service.update_table(
                    ctx, table.id, TableUpdate(name="Renamed", description="changed")
                ),
            )
        )
        await asyncio.sleep(_SETTLE)
        assert not rename.done(), "the update did not wait for the archive"
        await archiving.commit()

    with pytest.raises(TableArchivedError):
        await rename
    async with factory() as check:
        stored = await VirtualTableService(check).describe_table(ctx, table.id)
    assert (stored.name, stored.description) == ("People", None)
