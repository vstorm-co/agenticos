"""The Virtual Tables sweep: what leaves, what survives, and what it records (#1823).

It joins the retention sweep (`RetentionService.sweep`) rather than running beside it, so
these drive that one entry point on a frozen clock. Rows are inserted with explicit ages
so a boundary is exactly where the test puts it, and each class is checked from both
sides: the row that must go, and the one that must stay.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from app.core.config import settings
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.virtual_table import (
    VirtualTable,
    VirtualTableOutbox,
    VirtualTableReceipt,
    VirtualTableRecordHistory,
)
from app.repositories import retention_repo
from app.services import retention as retention_module
from app.services.retention import RetentionService
from tests.integration.virtual_table_support import make_org, make_table, make_user

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
SECRET = "cell-content-that-must-not-reach-the-audit-trail"


async def _tenant(db, name="orders"):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    table = await make_table(db, org=org, owner=owner, name=name)
    return owner, org, table


def _receipt(org, owner, key, *, age: timedelta) -> VirtualTableReceipt:
    return VirtualTableReceipt(
        organization_id=org.id,
        principal_id=owner.id,
        operation="record.create",
        operation_key=key,
        payload_hash="h",
        outcome={"record": {"values": {"c": SECRET}}},
        created_at=NOW - age,
    )


def _history(org, table, *, age: timedelta) -> VirtualTableRecordHistory:
    return VirtualTableRecordHistory(
        organization_id=org.id,
        table_id=table.id,
        record_id=uuid.uuid4(),
        revision=1,
        operation="create",
        after={"c": SECRET},
        created_at=NOW - age,
    )


def _outbox(org, table, *, dispatched_age: timedelta | None) -> VirtualTableOutbox:
    return VirtualTableOutbox(
        organization_id=org.id,
        table_id=table.id,
        record_id=uuid.uuid4(),
        event_type="table.record.created",
        payload={},
        dispatched_at=None if dispatched_age is None else NOW - dispatched_age,
    )


async def _count(db, model, org) -> int:
    return await db.scalar(
        select(func.count()).select_from(model).where(model.organization_id == org.id)
    )


async def _sweep(db):
    return await RetentionService(db).sweep(now=NOW)


async def test_receipts_expire_after_their_lifetime_and_not_before(db):
    owner, org, _table = await _tenant(db)
    ttl = timedelta(hours=settings.TABLES_RECEIPT_TTL_HOURS)
    db.add_all(
        [
            _receipt(org, owner, "fresh", age=ttl - timedelta(minutes=1)),
            _receipt(org, owner, "expired", age=ttl + timedelta(minutes=1)),
            _receipt(org, owner, "ancient", age=timedelta(days=90)),
        ]
    )
    await db.flush()

    (result,) = await _sweep(db)

    assert result.removed == {"table_receipts": 2}
    kept = await db.scalars(select(VirtualTableReceipt.operation_key))
    assert list(kept) == ["fresh"]


async def test_only_dispatched_outbox_rows_leave_and_only_after_their_window(db):
    _owner, org, table = await _tenant(db)
    window = timedelta(days=settings.TABLES_OUTBOX_RETENTION_DAYS)
    rows = {
        "pending": _outbox(org, table, dispatched_age=None),
        "recent": _outbox(org, table, dispatched_age=window - timedelta(hours=1)),
        "old": _outbox(org, table, dispatched_age=window + timedelta(hours=1)),
    }
    db.add_all(rows.values())
    await db.flush()

    (result,) = await _sweep(db)

    assert result.removed == {"table_outbox": 1}
    survivors = set(await db.scalars(select(VirtualTableOutbox.id)))
    assert survivors == {rows["pending"].id, rows["recent"].id}


async def test_an_undispatched_outbox_row_survives_however_old(db):
    _owner, org, table = await _tenant(db)
    stale = _outbox(org, table, dispatched_age=None)
    stale.created_at = NOW - timedelta(days=3650)
    db.add(stale)
    await db.flush()

    assert await _sweep(db) == []

    assert await _count(db, VirtualTableOutbox, org) == 1


async def test_history_follows_its_window_for_a_live_or_deleted_record_alike(db):
    _owner, org, table = await _tenant(db)
    window = timedelta(days=settings.TABLES_HISTORY_RETENTION_DAYS)
    inside = _history(org, table, age=window - timedelta(days=1))
    outside = _history(org, table, age=window + timedelta(days=1))
    # No record row exists for either: history of a deleted record is not special.
    db.add_all([inside, outside])
    await db.flush()

    (result,) = await _sweep(db)

    assert result.removed == {"table_history": 1}
    assert set(await db.scalars(select(VirtualTableRecordHistory.id))) == {inside.id}


async def test_one_audit_entry_per_sweep_names_the_classes_and_counts_never_content(db):
    owner, org, table = await _tenant(db)
    ttl = timedelta(hours=settings.TABLES_RECEIPT_TTL_HOURS)
    db.add_all(
        [
            _receipt(org, owner, "a", age=ttl + timedelta(hours=1)),
            _receipt(org, owner, "b", age=ttl + timedelta(hours=2)),
            _history(org, table, age=timedelta(days=settings.TABLES_HISTORY_RETENTION_DAYS + 5)),
        ]
    )
    await db.flush()

    await _sweep(db)

    entries = list(
        await db.scalars(
            select(AppAdminAuditLog).where(
                AppAdminAuditLog.organization_id == org.id,
                AppAdminAuditLog.action == "retention.swept",
            )
        )
    )
    assert len(entries) == 1
    assert entries[0].details == {
        "removed": {"table_receipts": 2, "table_history": 1},
        "failed": [],
    }
    assert SECRET not in str(entries[0].details)


async def test_a_sweep_with_nothing_expired_removes_and_records_nothing(db):
    owner, org, table = await _tenant(db)
    db.add_all(
        [
            _receipt(org, owner, "fresh", age=timedelta(minutes=5)),
            _history(org, table, age=timedelta(days=1)),
            _outbox(org, table, dispatched_age=timedelta(hours=1)),
        ]
    )
    await db.flush()

    assert await _sweep(db) == []

    assert (
        await db.scalar(
            select(func.count())
            .select_from(AppAdminAuditLog)
            .where(AppAdminAuditLog.action == "retention.swept")
        )
        == 0
    )


async def test_each_organizations_rows_are_swept_on_their_own(db):
    ours_owner, ours, our_table = await _tenant(db, "ours")
    theirs_owner, theirs, their_table = await _tenant(db, "theirs")
    old = timedelta(days=settings.TABLES_HISTORY_RETENTION_DAYS + 1)
    db.add_all(
        [
            _history(ours, our_table, age=old),
            _history(theirs, their_table, age=old),
            _history(theirs, their_table, age=timedelta(days=1)),
        ]
    )
    await db.flush()

    removed = await retention_repo.delete_table_history(
        db, organization_id=ours.id, cutoff=NOW - timedelta(days=30), limit=100
    )

    assert removed == 1
    assert await _count(db, VirtualTableRecordHistory, ours) == 0
    assert await _count(db, VirtualTableRecordHistory, theirs) == 2
    assert ours_owner.id != theirs_owner.id


async def test_a_backlog_is_worked_off_in_batches_over_several_sweeps(db, monkeypatch):
    owner, org, _table = await _tenant(db)
    monkeypatch.setattr(retention_module, "BATCH", 2)
    monkeypatch.setattr(retention_module, "MAX_BATCHES", 2)
    expired = timedelta(hours=settings.TABLES_RECEIPT_TTL_HOURS + 1)
    db.add_all([_receipt(org, owner, f"k{n}", age=expired) for n in range(5)])
    await db.flush()

    (first,) = await _sweep(db)
    (second,) = await _sweep(db)

    assert first.removed == {"table_receipts": 4}
    assert second.removed == {"table_receipts": 1}
    assert await _count(db, VirtualTableReceipt, org) == 0


async def test_a_class_that_fails_is_named_and_the_others_still_sweep(db, monkeypatch):
    owner, org, table = await _tenant(db)

    async def broken(*args, **kwargs):
        raise RuntimeError("storage went away")

    monkeypatch.setattr(retention_repo, "delete_table_outbox", broken)
    db.add_all(
        [
            _receipt(org, owner, "old", age=timedelta(days=5)),
            _outbox(org, table, dispatched_age=timedelta(days=30)),
        ]
    )
    await db.flush()

    (result,) = await _sweep(db)

    assert result.failed == ["table_outbox"]
    assert result.removed == {"table_receipts": 1}
    entry = await db.scalar(
        select(AppAdminAuditLog.details).where(
            AppAdminAuditLog.organization_id == org.id,
            AppAdminAuditLog.action == "retention.swept",
        )
    )
    assert entry == {"removed": {"table_receipts": 1}, "failed": ["table_outbox"]}


async def test_a_table_is_never_removed_by_the_sweep(db):
    owner, org, table = await _tenant(db)
    db.add(_receipt(org, owner, "old", age=timedelta(days=5)))
    await db.flush()

    await _sweep(db)

    assert await db.scalar(select(func.count()).select_from(VirtualTable)) == 1
    assert table.id


async def test_receipts_and_outbox_are_removed_only_from_the_organization_asked_about(db):
    ours_owner, ours, our_table = await _tenant(db, "ours")
    theirs_owner, theirs, their_table = await _tenant(db, "theirs")
    db.add_all(
        [
            _receipt(ours, ours_owner, "a", age=timedelta(days=9)),
            _receipt(theirs, theirs_owner, "b", age=timedelta(days=9)),
            _outbox(ours, our_table, dispatched_age=timedelta(days=30)),
            _outbox(theirs, their_table, dispatched_age=timedelta(days=30)),
        ]
    )
    await db.flush()
    scope = {"organization_id": ours.id, "cutoff": NOW - timedelta(days=1), "limit": 100}

    assert await retention_repo.delete_table_receipts(db, **scope) == 1
    assert await retention_repo.delete_table_outbox(db, **scope) == 1

    assert await _count(db, VirtualTableReceipt, theirs) == 1
    assert await _count(db, VirtualTableOutbox, theirs) == 1


async def _fail_in_the_database(db, **kwargs) -> int:
    """A delete that fails the way a real one does: PostgreSQL rejects the statement.

    Unlike raising in Python, this aborts the transaction, which is what used to make every
    later class and the audit entry fail with InFailedSQLTransaction.
    """
    await db.execute(text("SELECT * FROM a_table_that_does_not_exist"))
    return 0


async def test_a_database_error_in_one_table_class_leaves_the_others_and_the_audit_intact(
    db, monkeypatch
):
    owner, org, table = await _tenant(db)
    db.add_all(
        [
            _receipt(org, owner, "old", age=timedelta(days=5)),
            _outbox(org, table, dispatched_age=timedelta(days=30)),
            _history(org, table, age=timedelta(days=settings.TABLES_HISTORY_RETENTION_DAYS + 5)),
        ]
    )
    await db.flush()
    monkeypatch.setattr(retention_repo, "delete_table_outbox", _fail_in_the_database)

    (result,) = await _sweep(db)

    assert result.failed == ["table_outbox"]
    assert result.removed == {"table_receipts": 1, "table_history": 1}
    # Before the failure and after it, both deleted; the failed class's row stays for the next pass.
    assert await _count(db, VirtualTableReceipt, org) == 0
    assert await _count(db, VirtualTableRecordHistory, org) == 0
    assert await _count(db, VirtualTableOutbox, org) == 1
    entry = await db.scalar(
        select(AppAdminAuditLog.details).where(
            AppAdminAuditLog.organization_id == org.id,
            AppAdminAuditLog.action == "retention.swept",
        )
    )
    assert entry == {
        "removed": {"table_receipts": 1, "table_history": 1},
        "failed": ["table_outbox"],
    }


async def test_a_database_error_in_an_older_class_no_longer_takes_the_table_classes_with_it(
    db, monkeypatch
):
    """The gap predates the table classes: any class failing in the database aborted the rest."""
    owner, org, _table = await _tenant(db)
    org.retention_days = {"workspaces": 1}
    db.add(_receipt(org, owner, "old", age=timedelta(days=5)))
    await db.flush()
    monkeypatch.setattr(retention_repo, "delete_workspaces", _fail_in_the_database)

    (result,) = await _sweep(db)

    assert result.failed == ["workspaces"]
    assert result.removed == {"table_receipts": 1}
    assert await _count(db, VirtualTableReceipt, org) == 0
    assert (
        await db.scalar(
            select(func.count())
            .select_from(AppAdminAuditLog)
            .where(
                AppAdminAuditLog.organization_id == org.id,
                AppAdminAuditLog.action == "retention.swept",
            )
        )
        == 1
    )


async def test_a_batch_that_fails_keeps_the_batches_before_it(db, monkeypatch):
    owner, org, _table = await _tenant(db)
    monkeypatch.setattr(retention_module, "BATCH", 2)
    expired = timedelta(hours=settings.TABLES_RECEIPT_TTL_HOURS + 1)
    db.add_all([_receipt(org, owner, f"k{n}", age=expired) for n in range(4)])
    await db.flush()
    real = retention_repo.delete_table_receipts
    calls = {"n": 0}

    async def second_batch_fails(db, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            return await _fail_in_the_database(db)
        return await real(db, **kwargs)

    monkeypatch.setattr(retention_repo, "delete_table_receipts", second_batch_fails)

    (result,) = await _sweep(db)

    assert result.failed == ["table_receipts"]
    assert await _count(db, VirtualTableReceipt, org) == 2
