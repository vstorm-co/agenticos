"""Schema storage admission is atomic and shares record writers' lock order."""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.locks import LockScope
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.virtual_table import (
    VirtualTable,
    VirtualTableOutbox,
    VirtualTableReceipt,
    VirtualTableRecordHistory,
    VirtualTableSchemaVersion,
)
from app.db.models.virtual_table_relation import VirtualTableRelation
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import (
    ColumnInput,
    RecordBatchCreate,
    RecordCreate,
    RecordUpdate,
    RecordUpsert,
    SchemaUpdate,
    TableCreate,
    TableRead,
)
from app.services.virtual_tables import VirtualTableService, quotas
from app.services.virtual_tables.exceptions import QuotaExceededError
from app.services.virtual_tables.receipts import payload_hash
from tests.integration.virtual_table_support import column, ctx_for, make_org, make_user

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _setup(
    engine: AsyncEngine,
) -> tuple[async_sessionmaker[AsyncSession], AuthContext, TableRead, TableRead]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        owner = await make_user(db)
        org = await make_org(db, owner=owner)
        ctx = ctx_for(owner, org)
        service = VirtualTableService(db)
        target = await service.create_table(
            ctx, TableCreate(name="Targets", columns=[column("Name", "text")])
        )
        source = await service.create_table(
            ctx, TableCreate(name="Source", columns=[column("Note", "text")])
        )
        await db.commit()
    return factory, ctx, source, target


@pytest.mark.parametrize(
    ("linked", "operation_key"),
    [(True, None), (True, "linked-create"), (False, "receipt-only-create")],
)
async def test_refused_create_rolls_back_definitions_and_receipt_before_audit(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    linked: bool,
    operation_key: str | None,
) -> None:
    factory, ctx, _source, target = await _setup(engine)
    body = TableCreate(
        name="private-name-from-refused-request",
        columns=[
            column("Target", "link", link_table_id=target.id) if linked else column("Note", "text")
        ],
    )
    normal_limit = settings.TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION
    monkeypatch.setattr(settings, "TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION", 1)
    async with factory() as db:
        # The independent refusal audit would deadlock if table.created held its
        # chain lock first. Catching and committing proves the service savepoint
        # also protects a caller that keeps using its request transaction.
        async with asyncio.timeout(5):
            with pytest.raises(QuotaExceededError) as caught:
                await VirtualTableService(db).create_table(ctx, body, operation_key=operation_key)
        await db.commit()
    assert caught.value.details == {"quota": "storage_bytes", "limit": 1}
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(VirtualTable)) == 2
        assert await db.scalar(select(func.count()).select_from(VirtualTableSchemaVersion)) == 2
        assert await db.scalar(select(func.count()).select_from(VirtualTableRelation)) == 0
        assert await db.scalar(select(func.count()).select_from(VirtualTableReceipt)) == 0
        assert await virtual_table_repo.storage_bytes(db, organization_id=ctx.organization_id) == 0
        audits = list(await db.scalars(select(AppAdminAuditLog).order_by(AppAdminAuditLog.seq)))
        assert [entry.action for entry in audits] == [
            "table.created",
            "table.created",
            "table.quota_refused",
        ]
        assert audits[-1].details == caught.value.details
        assert body.name not in str(audits[-1].details)

    # The refused key and name are reusable, and a completed receipt can still
    # replay after an operator lowers the ceiling below existing usage.
    monkeypatch.setattr(settings, "TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION", normal_limit)
    async with factory() as db:
        created = await VirtualTableService(db).create_table(ctx, body, operation_key=operation_key)
        await db.commit()
    if operation_key is not None:
        monkeypatch.setattr(settings, "TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION", 1)
        async with factory() as db:
            replay = await VirtualTableService(db).create_table(
                ctx, body, operation_key=operation_key
            )
            await db.commit()
            assert replay == created
            assert await db.scalar(select(func.count()).select_from(VirtualTable)) == 3
            assert await db.scalar(select(func.count()).select_from(AppAdminAuditLog)) == 4


@pytest.mark.parametrize("retype", [False, True])
async def test_schema_quota_refusal_rolls_back_retype_and_definition_together(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, retype: bool
) -> None:
    factory, ctx, source, target = await _setup(engine)
    key = str(source.columns[0].id)
    async with factory() as db:
        record = await VirtualTableService(db).create_record(
            ctx, source.id, RecordCreate(values={key: "1"}), operation_key="seed"
        )
        await db.commit()
        used = await virtual_table_repo.storage_bytes(db, organization_id=ctx.organization_id)
    body = SchemaUpdate(
        expected_version=1,
        columns=[
            column("Note", "number" if retype else "text", id=source.columns[0].id),
            column("Target", "link", link_table_id=target.id),
        ],
    )
    normal_limit = settings.TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION
    monkeypatch.setattr(settings, "TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION", used)
    async with factory() as db:
        async with asyncio.timeout(5):
            with pytest.raises(QuotaExceededError):
                await VirtualTableService(db).update_schema(ctx, source.id, body)
        await db.commit()
    async with factory() as db:
        service = VirtualTableService(db)
        current = await service.describe_table(ctx, source.id)
        assert current.schema_version == 1 and current.columns == source.columns
        row = await service.get_record(ctx, source.id, record.record.id)
        assert row.revision == 1 and row.values == {key: "1"}
        assert await db.scalar(select(func.count()).select_from(VirtualTableSchemaVersion)) == 2
        assert await db.scalar(select(func.count()).select_from(VirtualTableRelation)) == 0
        assert await db.scalar(select(func.count()).select_from(VirtualTableRecordHistory)) == 1
        assert await db.scalar(select(func.count()).select_from(VirtualTableOutbox)) == 1
        assert await db.scalar(select(func.count()).select_from(VirtualTableReceipt)) == 1
        assert (
            await virtual_table_repo.storage_bytes(db, organization_id=ctx.organization_id) == used
        )
        refusal = await db.scalar(
            select(AppAdminAuditLog).where(AppAdminAuditLog.action == "table.quota_refused")
        )
        assert refusal is not None
        assert refusal.target_type == "table" and refusal.target_id == str(source.id)
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AppAdminAuditLog)
                .where(AppAdminAuditLog.action == "table.schema_changed")
            )
            == 0
        )

    monkeypatch.setattr(settings, "TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION", normal_limit)
    async with factory() as db:
        changed = await VirtualTableService(db).update_schema(ctx, source.id, body)
        await db.commit()
    monkeypatch.setattr(settings, "TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION", 1)
    async with factory() as db:
        unchanged = await VirtualTableService(db).update_schema(
            ctx,
            source.id,
            SchemaUpdate(
                expected_version=changed.schema_version,
                columns=[
                    ColumnInput(**item.model_dump(exclude={"revision"})) for item in changed.columns
                ],
            ),
        )
        await db.commit()
        assert unchanged.schema_version == changed.schema_version == 2
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AppAdminAuditLog)
                .where(AppAdminAuditLog.action == "table.schema_changed")
            )
            == 1
        )


async def test_table_create_and_schema_change_share_one_storage_reservation(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, ctx, source, target = await _setup(engine)
    async with factory() as db:
        await VirtualTableService(db).create_table(
            ctx,
            TableCreate(name="Seed", columns=[column("Target", "link", link_table_id=target.id)]),
        )
        await db.commit()
        used = await virtual_table_repo.storage_bytes(db, organization_id=ctx.organization_id)
    assert used > 0
    # Leave room for PostgreSQL's row representation: a just-inserted definition
    # can measure a few bytes larger. There is still room for only one more row.
    limit = used * 2 + used // 2
    monkeypatch.setattr(settings, "TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION", limit)

    async def attempt(*, create: bool) -> bool:
        async with factory() as db:
            service = VirtualTableService(db)
            linked = column("Target", "link", link_table_id=target.id)
            try:
                if create:
                    await service.create_table(ctx, TableCreate(name="Another", columns=[linked]))
                else:
                    await service.update_schema(
                        ctx,
                        source.id,
                        SchemaUpdate(
                            expected_version=1,
                            columns=[column("Note", "text", id=source.columns[0].id), linked],
                        ),
                    )
                await db.commit()
            except QuotaExceededError:
                await db.rollback()
                return False
            return True

    async with asyncio.timeout(10):
        outcomes = await asyncio.gather(attempt(create=True), attempt(create=False))
    assert sorted(outcomes) == [False, True]
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(VirtualTableRelation)) == 2
        assert (
            await virtual_table_repo.storage_bytes(db, organization_id=ctx.organization_id) <= limit
        )


@pytest.mark.parametrize(
    "operation", ["create", "update", "upsert", "batch", "keyed_batch", "schema"]
)
async def test_a_storage_waiter_does_not_hold_the_table_lock(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    factory, ctx, source, _target = await _setup(engine)
    key = str(source.columns[0].id)
    async with factory() as db:
        record = await VirtualTableService(db).create_record(
            ctx, source.id, RecordCreate(external_id="seed", values={key: "before"})
        )
        await db.commit()

    async with factory() as holding, factory() as writing:
        await quotas.lock_storage(holding, ctx)
        reached = asyncio.Event()
        original = quotas.hold_subject

        async def signal_storage(db: AsyncSession, scope: LockScope, subject: UUID) -> None:
            if db is writing and scope == LockScope.VIRTUAL_TABLE_STORAGE_PER_ORG:
                reached.set()
            await original(db, scope, subject)

        monkeypatch.setattr(quotas, "hold_subject", signal_storage)

        async def write() -> None:
            service = VirtualTableService(writing)
            values = {key: "after"}
            if operation == "create":
                await service.create_record(ctx, source.id, RecordCreate(values=values))
            elif operation == "update":
                await service.update_record(
                    ctx,
                    source.id,
                    record.record.id,
                    RecordUpdate(expected_revision=1, values=values),
                )
            elif operation == "upsert":
                await service.upsert_record(
                    ctx, source.id, "seed", RecordUpsert(expected_revision=1, values=values)
                )
            elif operation in {"batch", "keyed_batch"}:
                batch = RecordBatchCreate(records=[RecordCreate(values=values)])
                if operation == "keyed_batch":
                    await service.write_batch(ctx, source.id, batch, operation_key="lock-probe")
                else:
                    await service.create_records(ctx, source.id, batch)
            else:
                await service.update_schema(
                    ctx,
                    source.id,
                    SchemaUpdate(
                        expected_version=1,
                        columns=[column("Renamed", "text", id=source.columns[0].id)],
                    ),
                )
            await writing.commit()

        pending = asyncio.create_task(write())
        try:
            await asyncio.wait_for(reached.wait(), timeout=5)
            assert not pending.done()
            # If the waiter took SHARE/UPDATE first, this NOWAIT raises. The
            # storage holder must be free to acquire its schema lock and commit.
            await holding.execute(
                select(VirtualTable)
                .where(VirtualTable.id == source.id)
                .with_for_update(nowait=True)
            )
            if operation == "keyed_batch":
                # A batch receipt must not be claimed before its storage reservation:
                # the storage holder must still be able to claim this same key.
                batch = RecordBatchCreate(records=[RecordCreate(values={key: "after"})])
                claimed = await asyncio.wait_for(
                    virtual_table_repo.claim_receipt(
                        holding,
                        organization_id=ctx.organization_id,
                        principal_id=ctx.subject_id,
                        operation="record.batch",
                        operation_key="lock-probe",
                        payload_hash=payload_hash(
                            {"table_id": source.id, **batch.model_dump(mode="json")}
                        ),
                    ),
                    timeout=5,
                )
                assert claimed is not None
            # The probe's claim is deliberately discarded so the writer runs normally.
            await holding.rollback()
            await asyncio.wait_for(pending, timeout=5)
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
