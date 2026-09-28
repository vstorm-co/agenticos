"""What one change stores, however large the record is (#1823).

An edit of one cell of a large record used to write two full snapshots to history and,
with an idempotency key, a third copy to a receipt, so a loop of tiny requests cost the
size of the record each time. History now keeps only the cells that changed, and the
record limit bounds the one-off snapshots a create and a delete keep.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text

from app.core.config import settings
from app.db.models.virtual_table import VirtualTableReceipt, VirtualTableRecordHistory
from app.schemas.virtual_table import RecordCreate, RecordUpdate, TableCreate
from app.services.virtual_tables import VirtualTableService
from tests.integration.virtual_table_support import column, ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio

BIG = "x" * 50_000


async def _setup(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    service = VirtualTableService(db)
    ctx = ctx_for(owner, org)
    table = await service.create_table(
        ctx,
        TableCreate(
            name="Docs",
            columns=[
                column("Body", "long_text"),
                column("Status", "text"),
                column("Owner", "text"),
            ],
        ),
    )
    ids = {c.label: str(c.id) for c in table.columns}
    return service, ctx, table, ids


async def _history_bytes(db, operation: str) -> list[int]:
    rows = await db.execute(
        text(
            "SELECT coalesce(octet_length(before::text), 0) + coalesce(octet_length(after::text), 0)"
            " FROM virtual_table_record_history WHERE operation = :op ORDER BY revision"
        ),
        {"op": operation},
    )
    return [row[0] for row in rows]


async def test_editing_one_cell_of_a_large_record_stores_only_that_cell(db):
    service, ctx, table, ids = await _setup(db)
    written = await service.create_record(
        ctx, table.id, RecordCreate(values={ids["Body"]: BIG, ids["Status"]: "draft"})
    )

    for revision, status in enumerate(("review", "draft", "review"), start=1):
        await service.update_record(
            ctx,
            table.id,
            written.record.id,
            RecordUpdate(expected_revision=revision, values={ids["Status"]: status}),
            operation_key=f"edit-{revision}",
        )

    updates = (
        await db.scalars(
            select(VirtualTableRecordHistory)
            .where(VirtualTableRecordHistory.operation == "update")
            .order_by(VirtualTableRecordHistory.revision)
        )
    ).all()
    assert [(u.before, u.after) for u in updates] == [
        ({ids["Status"]: "draft"}, {ids["Status"]: "review"}),
        ({ids["Status"]: "review"}, {ids["Status"]: "draft"}),
        ({ids["Status"]: "draft"}, {ids["Status"]: "review"}),
    ]
    sizes = await _history_bytes(db, "update")
    assert len(sizes) == 3 and max(sizes) < 300
    assert min(await _history_bytes(db, "create")) > 50_000


async def test_a_cell_that_was_empty_or_is_cleared_is_absent_from_that_side(db):
    service, ctx, table, ids = await _setup(db)
    written = await service.create_record(ctx, table.id, RecordCreate(values={ids["Body"]: BIG}))

    added = await service.update_record(
        ctx,
        table.id,
        written.record.id,
        RecordUpdate(expected_revision=1, values={ids["Owner"]: "ada"}),
    )
    await service.update_record(
        ctx,
        table.id,
        written.record.id,
        RecordUpdate(expected_revision=added.record.revision, values={ids["Owner"]: None}),
    )

    updates = (
        await db.scalars(
            select(VirtualTableRecordHistory)
            .where(VirtualTableRecordHistory.operation == "update")
            .order_by(VirtualTableRecordHistory.revision)
        )
    ).all()
    assert [(u.before, u.after) for u in updates] == [
        ({}, {ids["Owner"]: "ada"}),
        ({ids["Owner"]: "ada"}, {}),
    ]


async def test_the_create_and_delete_snapshots_are_bounded_by_the_record_limit(db, monkeypatch):
    service, ctx, table, ids = await _setup(db)
    written = await service.create_record(
        ctx, table.id, RecordCreate(values={ids["Body"]: BIG}), operation_key="k"
    )
    limit = settings.TABLES_MAX_RECORD_BYTES

    await service.delete_record(ctx, table.id, written.record.id, expected_revision=1)

    (create,) = await _history_bytes(db, "create")
    (delete,) = await _history_bytes(db, "delete")
    assert 50_000 < create <= limit + 200
    assert 50_000 < delete <= limit + 200
    receipt = await db.scalar(
        text("SELECT octet_length(outcome::text) FROM virtual_table_receipts")
    )
    assert receipt <= limit + 1_000
    assert await db.scalar(select(func.count()).select_from(VirtualTableReceipt)) == 1


async def test_deleting_a_record_over_the_limit_succeeds_and_keeps_only_a_marker(db, monkeypatch):
    """A record written before the limit was lowered is still deletable, without a huge copy."""
    from app.services.virtual_tables import quotas

    service, ctx, table, ids = await _setup(db)
    written = await service.create_record(ctx, table.id, RecordCreate(values={ids["Body"]: BIG}))
    size = quotas.record_size(written.record.values)
    monkeypatch.setattr(settings, "TABLES_MAX_RECORD_BYTES", 100)

    await service.delete_record(ctx, table.id, written.record.id, expected_revision=1)

    (row,) = (
        await db.scalars(
            select(VirtualTableRecordHistory).where(VirtualTableRecordHistory.operation == "delete")
        )
    ).all()
    assert row.before == {"omitted": {"bytes": size, "limit": 100}}
    assert row.after is None
    assert min(await _history_bytes(db, "delete")) < 200


async def test_deleting_a_record_at_or_under_the_limit_keeps_its_whole_before(db, monkeypatch):
    from app.services.virtual_tables import quotas

    service, ctx, table, ids = await _setup(db)
    values = {ids["Status"]: "draft"}
    written = await service.create_record(ctx, table.id, RecordCreate(values=values))
    monkeypatch.setattr(settings, "TABLES_MAX_RECORD_BYTES", quotas.record_size(values))

    await service.delete_record(ctx, table.id, written.record.id, expected_revision=1)

    row = await db.scalar(
        select(VirtualTableRecordHistory).where(VirtualTableRecordHistory.operation == "delete")
    )
    assert row.before == values
