"""Idempotency, atomicity and races, against a real database.

Three guarantees, none of which a mock can show:

- a retried keyed write returns the stored outcome and writes nothing again, even
  after the record has moved on, and never to a principal who lost access;
- a change, its history row, its created event and its receipt commit or roll back
  together;
- two writers racing for one external id, one revision, one name or one operation
  key produce one winner and a typed loser, never a duplicate.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.db.models.resource_grant import GrantLevel
from app.db.models.virtual_table import (
    VirtualTableOutbox,
    VirtualTableReceipt,
    VirtualTableRecord,
    VirtualTableRecordHistory,
)
from app.repositories import resource_grant_repo, virtual_table_repo
from app.schemas.virtual_table import (
    RecordCreate,
    RecordUpdate,
    RecordUpsert,
    TableCreate,
)
from app.services.access import TABLE
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables.exceptions import (
    IdempotencyKeyReuseError,
    RevisionConflictError,
    RevisionRequiredError,
)
from tests.integration.virtual_table_support import (
    cid,
    ctx_for,
    make_org,
    make_user,
    orders_table,
)

pytestmark = pytest.mark.anyio


async def _rows(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def _setup(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    service = VirtualTableService(db)
    ctx = ctx_for(owner, org)
    return service, ctx, await orders_table(service, ctx), org


async def test_a_retried_create_returns_the_stored_outcome_and_writes_nothing_again(db):
    service, ctx, table, _org = await _setup(db)
    body = RecordCreate(external_id="A-1", values={cid(table, "Customer"): "Acme"})

    first = await service.create_record(ctx, table.id, body, operation_key="k-1")
    retry = await service.create_record(ctx, table.id, body, operation_key="k-1")

    assert (first.created, first.replayed) == (True, False)
    assert (retry.created, retry.replayed) == (True, True)
    assert retry.record == first.record
    assert await _rows(db, VirtualTableRecord) == 1
    assert await _rows(db, VirtualTableRecordHistory) == 1
    assert await _rows(db, VirtualTableOutbox) == 1
    assert await _rows(db, VirtualTableReceipt) == 1


async def test_a_retry_returns_the_original_answer_even_after_the_record_changed(db):
    service, ctx, table, _org = await _setup(db)
    customer = cid(table, "Customer")
    body = RecordUpsert(values={customer: "Acme"})
    first = await service.upsert_record(ctx, table.id, "A-1", body, operation_key="k")
    await service.upsert_record(
        ctx, table.id, "A-1", RecordUpsert(values={customer: "Acme 2"}, expected_revision=1)
    )

    retry = await service.upsert_record(ctx, table.id, "A-1", body, operation_key="k")

    assert retry.replayed and retry.created
    assert retry.record.revision == 1 and retry.record.values == {customer: "Acme"}
    assert first.record == retry.record


async def test_reusing_a_key_for_a_different_request_is_refused_and_writes_nothing(db):
    service, ctx, table, _org = await _setup(db)
    customer = cid(table, "Customer")
    await service.create_record(
        ctx, table.id, RecordCreate(values={customer: "Acme"}), operation_key="k"
    )

    with pytest.raises(IdempotencyKeyReuseError) as raised:
        await service.create_record(
            ctx, table.id, RecordCreate(values={customer: "Other"}), operation_key="k"
        )

    assert raised.value.details == {"operation": "record.create"}
    assert await _rows(db, VirtualTableRecord) == 1


async def test_a_key_is_scoped_to_the_principal_the_operation_and_the_table(db):
    service, ctx, table, org = await _setup(db)
    body = RecordCreate(values={})
    colleague = await make_user(db)
    other = ctx_for(colleague, org, "admin")
    second_table = await service.create_table(ctx, TableCreate(name="Second"))

    await service.create_record(ctx, table.id, body, operation_key="k")
    by_someone_else = await service.create_record(other, table.id, body, operation_key="k")
    upserted = await service.upsert_record(
        ctx, table.id, "A-1", RecordUpsert(values={}), operation_key="k"
    )
    with pytest.raises(IdempotencyKeyReuseError):
        await service.create_record(ctx, second_table.id, body, operation_key="k")

    assert not by_someone_else.replayed and not upserted.replayed
    assert await _rows(db, VirtualTableRecord) == 3
    assert await _rows(db, VirtualTableReceipt) == 3


async def test_a_refused_write_leaves_no_receipt_so_the_corrected_retry_succeeds(db):
    service, ctx, table, _org = await _setup(db)
    quantity = cid(table, "Quantity")
    written = await service.create_record(ctx, table.id, RecordCreate(values={quantity: 1}))

    with pytest.raises(RevisionConflictError):
        await service.update_record(
            ctx,
            table.id,
            written.record.id,
            RecordUpdate(expected_revision=9, values={quantity: 2}),
            operation_key="fix",
        )
    assert await _rows(db, VirtualTableReceipt) == 0

    fixed = await service.update_record(
        ctx,
        table.id,
        written.record.id,
        RecordUpdate(expected_revision=1, values={quantity: 2}),
        operation_key="fix",
    )
    assert fixed.record.values == {quantity: 2} and not fixed.replayed


async def test_a_retried_delete_succeeds_but_an_unkeyed_second_delete_is_not_found(db):
    service, ctx, table, _org = await _setup(db)
    written = await service.create_record(ctx, table.id, RecordCreate(values={}))
    args = (ctx, table.id, written.record.id)

    await service.delete_record(*args, expected_revision=1, operation_key="del")
    await service.delete_record(*args, expected_revision=1, operation_key="del")
    with pytest.raises(NotFoundError):
        await service.delete_record(*args, expected_revision=1)

    assert await _rows(db, VirtualTableRecordHistory) == 2
    assert await _rows(db, VirtualTableReceipt) == 1


async def test_a_receipt_is_not_replayed_to_a_principal_who_lost_access(db):
    service, ctx, table, org = await _setup(db)
    colleague = await make_user(db)
    editor = ctx_for(colleague, org, "viewer")
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=table.id,
        level=GrantLevel.EDIT,
    )
    body = RecordCreate(external_id="A-1", values={})
    await service.create_record(editor, table.id, body, operation_key="k")

    await resource_grant_repo.revoke(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=table.id,
    )

    with pytest.raises(NotFoundError):
        await service.create_record(editor, table.id, body, operation_key="k")
    assert await _rows(db, VirtualTableReceipt) == 1


async def test_a_replay_still_answers_after_the_table_was_archived(db):
    service, ctx, table, _org = await _setup(db)
    body = RecordCreate(external_id="A-1", values={})
    await service.create_record(ctx, table.id, body, operation_key="k")
    await service.archive_table(ctx, table.id)

    retry = await service.create_record(ctx, table.id, body, operation_key="k")

    assert retry.replayed


@pytest.mark.parametrize("failing", ["add_history", "add_outbox", "set_receipt_outcome"])
async def test_a_failure_after_the_write_rolls_back_the_record_history_event_and_receipt(
    db, monkeypatch, failing
):
    service, ctx, table, _org = await _setup(db)

    async def boom(*args, **kwargs):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(virtual_table_repo, failing, boom)

    with pytest.raises(RuntimeError):
        await service.create_record(
            ctx, table.id, RecordCreate(external_id="A-1", values={}), operation_key="k"
        )

    for model in (
        VirtualTableRecord,
        VirtualTableRecordHistory,
        VirtualTableOutbox,
        VirtualTableReceipt,
    ):
        assert await _rows(db, model) == 0


async def test_a_failed_update_leaves_the_revision_and_values_as_they_were(db, monkeypatch):
    service, ctx, table, _org = await _setup(db)
    quantity = cid(table, "Quantity")
    written = await service.create_record(ctx, table.id, RecordCreate(values={quantity: 1}))

    async def boom(*args, **kwargs):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(virtual_table_repo, "add_history", boom)
    with pytest.raises(RuntimeError):
        await service.update_record(
            ctx,
            table.id,
            written.record.id,
            RecordUpdate(expected_revision=1, values={quantity: 2}),
            operation_key="k",
        )
    monkeypatch.undo()

    current = await service.get_record(ctx, table.id, written.record.id)
    assert (current.revision, current.values) == (1, {quantity: 1})
    assert await _rows(db, VirtualTableReceipt) == 0


async def _committed_table(engine: AsyncEngine):
    """A table and two members, committed, so separate sessions can race over them."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        owner = await make_user(setup)
        org = await make_org(setup, owner=owner)
        ctx = ctx_for(owner, org)
        table = await orders_table(VirtualTableService(setup), ctx)
        await setup.commit()
    return factory, ctx, table


async def _in_own_session(factory, work):
    async with factory() as session:
        try:
            result = await work(VirtualTableService(session))
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


async def test_concurrent_upserts_of_one_external_id_create_exactly_one_record(
    engine: AsyncEngine,
):
    factory, ctx, table = await _committed_table(engine)
    customer = cid(table, "Customer")

    async def upsert(name: str):
        return await _in_own_session(
            factory,
            lambda service: service.upsert_record(
                ctx, table.id, "A-1", RecordUpsert(values={customer: name})
            ),
        )

    results = await asyncio.gather(
        *(upsert(f"writer {n}") for n in range(8)), return_exceptions=True
    )

    created = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(created) == 1 and created[0].created
    assert len(refused) == 7 and all(isinstance(r, RevisionRequiredError) for r in refused)
    async with factory() as check:
        assert await _rows(check, VirtualTableRecord) == 1
        assert await _rows(check, VirtualTableOutbox) == 1
        assert await _rows(check, VirtualTableRecordHistory) == 1


async def test_concurrent_retries_of_one_keyed_upsert_agree_on_one_record(engine: AsyncEngine):
    factory, ctx, table = await _committed_table(engine)
    body = RecordUpsert(values={cid(table, "Customer"): "Acme"})

    results = await asyncio.gather(
        *(
            _in_own_session(
                factory,
                lambda service: service.upsert_record(
                    ctx, table.id, "A-1", body, operation_key="import-1"
                ),
            )
            for _ in range(6)
        )
    )

    assert sum(1 for r in results if not r.replayed) == 1
    assert len({r.record.id for r in results}) == 1
    assert all(r.created for r in results)
    async with factory() as check:
        assert await _rows(check, VirtualTableRecord) == 1
        assert await _rows(check, VirtualTableReceipt) == 1
        assert await _rows(check, VirtualTableOutbox) == 1


async def test_concurrent_use_of_one_key_for_different_requests_has_one_winner(
    engine: AsyncEngine,
):
    factory, ctx, table = await _committed_table(engine)
    customer = cid(table, "Customer")

    def create(name: str):
        return _in_own_session(
            factory,
            lambda service: service.create_record(
                ctx, table.id, RecordCreate(values={customer: name}), operation_key="k"
            ),
        )

    results = await asyncio.gather(create("a"), create("b"), return_exceptions=True)

    assert sum(isinstance(r, IdempotencyKeyReuseError) for r in results) == 1
    async with factory() as check:
        assert await _rows(check, VirtualTableRecord) == 1


async def test_concurrent_updates_from_one_revision_let_exactly_one_win(engine: AsyncEngine):
    factory, ctx, table = await _committed_table(engine)
    quantity = cid(table, "Quantity")
    written = await _in_own_session(
        factory,
        lambda service: service.create_record(ctx, table.id, RecordCreate(values={quantity: 0})),
    )

    def update(value: int):
        return _in_own_session(
            factory,
            lambda service: service.update_record(
                ctx,
                table.id,
                written.record.id,
                RecordUpdate(expected_revision=1, values={quantity: value}),
            ),
        )

    results = await asyncio.gather(*(update(n) for n in range(1, 6)), return_exceptions=True)

    winners = [r for r in results if not isinstance(r, BaseException)]
    losers = [r for r in results if isinstance(r, RevisionConflictError)]
    assert len(winners) == 1 and len(losers) == 4
    async with factory() as check:
        final = await VirtualTableService(check).get_record(ctx, table.id, written.record.id)
        assert final.revision == 2
        assert final.values == {quantity: winners[0].record.values[quantity]}
        assert await _rows(check, VirtualTableRecordHistory) == 2


async def test_concurrent_creates_of_one_table_name_have_one_winner(engine: AsyncEngine):
    factory, ctx, _table = await _committed_table(engine)

    results = await asyncio.gather(
        *(
            _in_own_session(
                factory, lambda service: service.create_table(ctx, TableCreate(name="Contested"))
            )
            for _ in range(4)
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(r, BaseException) for r in results) == 1
    assert all(isinstance(r, AlreadyExistsError) for r in results if isinstance(r, BaseException))
