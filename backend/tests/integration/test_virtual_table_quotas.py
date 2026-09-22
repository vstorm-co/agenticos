"""What one organization may store, and that a refusal is audited without content.

These commit their data and open a session per call, because a refusal writes its audit
entry in a session of its own: the refused request rolls back, and an entry written in
its transaction would go with it. A test that kept everything in one uncommitted session
could not see that the entry survives.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import settings
from app.core.exceptions import AlreadyExistsError
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.virtual_table import VirtualTableRecord
from app.schemas.virtual_table import (
    RecordCreate,
    RecordUpdate,
    RecordUpsert,
    TableCreate,
)
from app.services.virtual_tables import VirtualTableService, quotas
from app.services.virtual_tables.exceptions import QuotaExceededError, RevisionRequiredError
from tests.integration.virtual_table_support import column, ctx_for, make_org, make_user

pytestmark = [pytest.mark.anyio, pytest.mark.security]

SECRET_TEXT = "a-value-that-must-never-appear-in-an-audit-entry"


async def _tenant(factory):
    async with factory() as setup:
        owner = await make_user(setup)
        org = await make_org(setup, owner=owner)
        await setup.commit()
    return ctx_for(owner, org)


async def _call(factory, work):
    async with factory() as session:
        try:
            result = await work(VirtualTableService(session))
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


async def _table(factory, ctx, name="People"):
    return await _call(
        factory,
        lambda service: service.create_table(
            ctx, TableCreate(name=name, columns=[column("Note", "text")])
        ),
    )


async def _refusals(factory, ctx) -> list[dict]:
    async with factory() as session:
        rows = await session.scalars(
            select(AppAdminAuditLog.details).where(
                AppAdminAuditLog.organization_id == ctx.organization_id,
                AppAdminAuditLog.action == "table.quota_refused",
            )
        )
        return list(rows)


async def _records(factory) -> int:
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(VirtualTableRecord))


async def test_a_record_over_the_size_limit_is_refused_typed_and_audited_without_its_content(
    engine: AsyncEngine, monkeypatch
):
    monkeypatch.setattr(settings, "TABLES_MAX_RECORD_BYTES", 200)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(factory)
    table = await _table(factory, ctx)
    note = str(table.columns[0].id)

    with pytest.raises(QuotaExceededError) as raised:
        await _call(
            factory,
            lambda service: service.create_record(
                ctx, table.id, RecordCreate(values={note: SECRET_TEXT * 10})
            ),
        )

    error = raised.value
    assert (error.status_code, error.code) == (402, "QUOTA_EXCEEDED")
    assert error.details == {"quota": "record_bytes", "limit": 200}
    assert SECRET_TEXT not in error.message
    assert await _records(factory) == 0
    entries = await _refusals(factory, ctx)
    assert entries == [{"quota": "record_bytes", "limit": 200}]
    assert SECRET_TEXT not in str(entries)


async def test_a_record_may_be_exactly_the_limit_and_an_update_past_it_is_refused(
    engine: AsyncEngine, monkeypatch
):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(factory)
    table = await _table(factory, ctx)
    note = str(table.columns[0].id)
    overhead = len(('{"' + note + '":""}').encode())
    monkeypatch.setattr(settings, "TABLES_MAX_RECORD_BYTES", overhead + 10)

    written = await _call(
        factory,
        lambda service: service.create_record(ctx, table.id, RecordCreate(values={note: "x" * 10})),
    )
    with pytest.raises(QuotaExceededError):
        await _call(
            factory,
            lambda service: service.update_record(
                ctx,
                table.id,
                written.record.id,
                RecordUpdate(expected_revision=1, values={note: "x" * 11}),
            ),
        )

    async with factory() as check:
        stored = await VirtualTableService(check).get_record(ctx, table.id, written.record.id)
    assert (stored.revision, stored.values) == (1, {note: "x" * 10})


async def test_the_record_limit_counts_bytes_not_characters(engine: AsyncEngine, monkeypatch):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(factory)
    table = await _table(factory, ctx)
    note = str(table.columns[0].id)
    overhead = len(('{"' + note + '":""}').encode())
    monkeypatch.setattr(settings, "TABLES_MAX_RECORD_BYTES", overhead + 6)

    with pytest.raises(QuotaExceededError):
        await _call(
            factory,
            lambda service: service.create_record(
                ctx, table.id, RecordCreate(values={note: "é" * 4})
            ),
        )


async def test_the_table_limit_is_per_organization_and_counts_archived_tables(
    engine: AsyncEngine, monkeypatch
):
    monkeypatch.setattr(settings, "TABLES_MAX_PER_ORGANIZATION", 2)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ours, theirs = await _tenant(factory), await _tenant(factory)
    first = await _table(factory, ours, "One")
    await _table(factory, ours, "Two")
    await _call(factory, lambda service: service.archive_table(ours, first.id))

    with pytest.raises(QuotaExceededError) as raised:
        await _table(factory, ours, "Three")

    assert raised.value.details == {"quota": "tables", "limit": 2}
    assert (
        len((await _call(factory, lambda s: s.list_tables(ours, include_archived=True))).items) == 2
    )
    await _table(factory, theirs, "One")
    await _table(factory, theirs, "Two")
    assert await _refusals(factory, ours) == [{"quota": "tables", "limit": 2}]
    assert await _refusals(factory, theirs) == []


async def test_the_record_limit_is_per_table_and_per_organization(engine: AsyncEngine, monkeypatch):
    monkeypatch.setattr(settings, "TABLES_MAX_RECORDS_PER_TABLE", 3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ours, theirs = await _tenant(factory), await _tenant(factory)
    table, other_table = await _table(factory, ours), await _table(factory, ours, "Other")
    foreign = await _table(factory, theirs)
    for n in range(3):
        await _call(
            factory,
            lambda service, n=n: service.create_record(
                ours, table.id, RecordCreate(external_id=f"r{n}", values={})
            ),
        )

    for refused in (
        lambda service: service.create_record(ours, table.id, RecordCreate(values={})),
        lambda service: service.upsert_record(ours, table.id, "new", RecordUpsert(values={})),
    ):
        with pytest.raises(QuotaExceededError) as raised:
            await _call(factory, refused)
        assert raised.value.details == {"quota": "records", "limit": 3}

    # The other table of the same organization, and another organization, are unaffected.
    for target, who in ((other_table, ours), (foreign, theirs)):
        for _ in range(3):
            await _call(
                factory,
                lambda service, target=target, who=who: service.create_record(
                    who, target.id, RecordCreate(values={})
                ),
            )
    assert len(await _refusals(factory, ours)) == 2
    assert await _refusals(factory, theirs) == []


async def test_a_full_table_still_accepts_updates_to_its_records(engine: AsyncEngine, monkeypatch):
    monkeypatch.setattr(settings, "TABLES_MAX_RECORDS_PER_TABLE", 1)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(factory)
    table = await _table(factory, ctx)
    note = str(table.columns[0].id)
    written = await _call(
        factory,
        lambda service: service.upsert_record(ctx, table.id, "only", RecordUpsert(values={})),
    )

    changed = await _call(
        factory,
        lambda service: service.upsert_record(
            ctx,
            table.id,
            "only",
            RecordUpsert(values={note: "edited"}, expected_revision=written.record.revision),
        ),
    )

    assert changed.record.revision == 2


async def test_concurrent_creates_cannot_pass_the_record_limit_together(
    engine: AsyncEngine, monkeypatch
):
    """Each would read 'two of three' and insert; the count lock makes the check one step."""
    monkeypatch.setattr(settings, "TABLES_MAX_RECORDS_PER_TABLE", 3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(factory)
    table = await _table(factory, ctx)

    results = await asyncio.gather(
        *(
            _call(
                factory,
                lambda service: service.create_record(ctx, table.id, RecordCreate(values={})),
            )
            for _ in range(8)
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(r, BaseException) for r in results) == 3
    assert all(isinstance(r, QuotaExceededError) for r in results if isinstance(r, BaseException))
    assert await _records(factory) == 3


async def test_concurrent_table_creates_cannot_pass_the_table_limit_together(
    engine: AsyncEngine, monkeypatch
):
    monkeypatch.setattr(settings, "TABLES_MAX_PER_ORGANIZATION", 2)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(factory)

    results = await asyncio.gather(
        *(_table(factory, ctx, f"T{n}") for n in range(6)), return_exceptions=True
    )

    assert sum(not isinstance(r, BaseException) for r in results) == 2
    assert all(isinstance(r, QuotaExceededError) for r in results if isinstance(r, BaseException))


async def test_a_burst_of_refusals_never_waits_on_the_pool_the_requests_hold(
    engine: AsyncEngine, monkeypatch
):
    """Each refused request holds a pooled connection while its audit entry is written.

    With the audit on the same pool, a burst larger than the pool has every request waiting
    for a second connection until the timeout, and they answer 500 instead of the refusal.
    The pool here is deliberately tiny and the timeout short, and the loop is claimed the
    way the API's is, which is what makes `get_db_context` reach for that pool.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db import session as db_session

    monkeypatch.setattr(settings, "TABLES_MAX_RECORD_BYTES", 1)
    ordinary = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(ordinary)
    table = await _table(ordinary, ctx)
    tiny_engine = create_async_engine(engine.url, pool_size=2, max_overflow=0, pool_timeout=1)
    tiny = async_sessionmaker(tiny_engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "async_session_maker", tiny)
    db_session.claim_pooled_engines()
    try:
        results = await asyncio.gather(
            *(
                _call(
                    tiny,
                    lambda service: service.create_record(
                        ctx, table.id, RecordCreate(values={str(table.columns[0].id): "too big"})
                    ),
                )
                for _ in range(8)
            ),
            return_exceptions=True,
        )
    finally:
        db_session.release_pooled_engines()
        await tiny_engine.dispose()

    assert [type(r).__name__ for r in results] == ["QuotaExceededError"] * 8
    assert len(await _refusals(ordinary, ctx)) == 8


async def test_a_burst_of_refusals_never_opens_more_than_the_gate_allows(
    engine: AsyncEngine, monkeypatch
):
    """The audit no longer shares the request's pool (the fix above), but is unbounded on its
    own: a burst opens one live connection per refused request. This pins the bound instead -
    the semaphore around the audit write - by holding each write open long enough that a
    larger burst than the gate would overlap if nothing were serialising them.
    """
    monkeypatch.setattr(settings, "TABLES_MAX_RECORD_BYTES", 1)
    ordinary = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(ordinary)
    table = await _table(ordinary, ctx)

    real_record_audit = quotas.record_audit
    in_flight = 0
    peak = 0

    async def slow_record_audit(*args, **kwargs):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.05)
            return await real_record_audit(*args, **kwargs)
        finally:
            in_flight -= 1

    monkeypatch.setattr(quotas, "record_audit", slow_record_audit)

    results = await asyncio.gather(
        *(
            _call(
                ordinary,
                lambda service: service.create_record(
                    ctx, table.id, RecordCreate(values={str(table.columns[0].id): "too big"})
                ),
            )
            for _ in range(10)
        ),
        return_exceptions=True,
    )

    assert [type(r).__name__ for r in results] == ["QuotaExceededError"] * 10
    assert peak <= quotas._MAX_CONCURRENT_AUDITS
    assert peak > 1, "the burst never overlapped, so this proves nothing about the bound"
    assert len(await _refusals(ordinary, ctx)) == 10


async def test_two_upserts_of_one_new_id_for_the_last_slot_create_once_and_never_refuse(
    engine: AsyncEngine, monkeypatch
):
    """The loser used to take the count lock after the winner filled the table, see it full
    and be refused (and audited as a refusal), when its own id was already there to update."""
    monkeypatch.setattr(settings, "TABLES_MAX_RECORDS_PER_TABLE", 3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(factory)
    table = await _table(factory, ctx)
    for n in range(2):
        await _call(
            factory,
            lambda service, n=n: service.upsert_record(
                ctx, table.id, f"seed{n}", RecordUpsert(values={})
            ),
        )

    results = await asyncio.gather(
        *(
            _call(
                factory,
                lambda service: service.upsert_record(
                    ctx, table.id, "the-last-slot", RecordUpsert(values={})
                ),
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    created = [r for r in results if not isinstance(r, BaseException)]
    others = [r for r in results if isinstance(r, BaseException)]
    assert len(created) == 1 and created[0].created
    assert len(others) == 1 and isinstance(others[0], RevisionRequiredError)
    assert await _records(factory) == 3
    assert await _refusals(factory, ctx) == []


async def test_an_upsert_waiting_on_a_rival_for_the_last_slot_updates_it_when_the_rival_commits(
    engine: AsyncEngine, monkeypatch
):
    """The same race with the interleaving fixed: the rival holds the slot, uncommitted."""
    monkeypatch.setattr(settings, "TABLES_MAX_RECORDS_PER_TABLE", 1)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(factory)
    table = await _table(factory, ctx)

    async with factory() as rival:
        await VirtualTableService(rival).upsert_record(
            ctx, table.id, "the-last-slot", RecordUpsert(values={})
        )
        waiting = asyncio.create_task(
            _call(
                factory,
                lambda service: service.upsert_record(
                    ctx, table.id, "the-last-slot", RecordUpsert(values={})
                ),
            )
        )
        await asyncio.sleep(0.4)
        assert not waiting.done(), "the second upsert did not wait for the first"
        await rival.commit()

    with pytest.raises(RevisionRequiredError):
        await waiting
    assert await _records(factory) == 1
    assert await _refusals(factory, ctx) == []


async def test_a_duplicate_id_on_a_full_table_is_already_exists_not_a_quota_refusal(
    engine: AsyncEngine, monkeypatch
):
    monkeypatch.setattr(settings, "TABLES_MAX_RECORDS_PER_TABLE", 2)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx = await _tenant(factory)
    table = await _table(factory, ctx)
    for external_id in ("a", "b"):
        await _call(
            factory,
            lambda service, e=external_id: service.create_record(
                ctx, table.id, RecordCreate(external_id=e, values={})
            ),
        )

    with pytest.raises(AlreadyExistsError):
        await _call(
            factory,
            lambda service: service.create_record(
                ctx, table.id, RecordCreate(external_id="a", values={})
            ),
        )
    assert await _refusals(factory, ctx) == []

    for new in (RecordCreate(external_id="c", values={}), RecordCreate(values={})):
        with pytest.raises(QuotaExceededError):
            await _call(factory, lambda service, new=new: service.create_record(ctx, table.id, new))
    assert len(await _refusals(factory, ctx)) == 2
    assert await _records(factory) == 2
