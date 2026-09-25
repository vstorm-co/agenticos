"""The Virtual Tables sweep: what leaves, what survives, and what it records (#1823).

It joins the retention sweep (`RetentionService.sweep`) rather than running beside it, so
these drive that one entry point on a frozen clock. Rows are inserted with explicit ages
so a boundary is exactly where the test puts it, and each class is checked from both
sides: the row that must go, and the one that must stay.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text

from app.core.config import settings
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.organization import OrganizationMember
from app.db.models.virtual_table import (
    VirtualTable,
    VirtualTableOutbox,
    VirtualTableReceipt,
    VirtualTableRecordHistory,
)
from app.repositories import member_repo, retention_repo
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


def _outbox(
    org, table, *, dispatched_age: timedelta | None, created_age: timedelta | None = None
) -> VirtualTableOutbox:
    row = VirtualTableOutbox(
        organization_id=org.id,
        table_id=table.id,
        record_id=uuid.uuid4(),
        event_type="table.record.created",
        payload={},
        dispatched_at=None if dispatched_age is None else NOW - dispatched_age,
    )
    if created_age is not None:
        row.created_at = NOW - created_age
    return row


async def _count(db, model, org) -> int:
    return await db.scalar(
        select(func.count()).select_from(model).where(model.organization_id == org.id)
    )


async def _audited(db, org) -> dict:
    """The details of the one `retention.swept` entry an organization's sweep wrote."""
    return await db.scalar(
        select(AppAdminAuditLog.details).where(
            AppAdminAuditLog.organization_id == org.id,
            AppAdminAuditLog.action == "retention.swept",
        )
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


async def test_an_undispatched_outbox_row_is_a_dead_letter_past_its_own_much_longer_window(db):
    """No consumer sets dispatched_at (#1785), so this is the only thing that ever removes
    one - a deliberate dead-letter cutoff, not a claim the event was delivered."""
    _owner, org, table = await _tenant(db)
    window = timedelta(days=settings.TABLES_OUTBOX_UNDISPATCHED_RETENTION_DAYS)
    fresh = _outbox(org, table, dispatched_age=None, created_age=window - timedelta(hours=1))
    stale = _outbox(org, table, dispatched_age=None, created_age=window + timedelta(hours=1))
    db.add_all([fresh, stale])
    await db.flush()

    (result,) = await _sweep(db)

    assert result.removed == {"table_outbox": 1}
    survivors = set(await db.scalars(select(VirtualTableOutbox.id)))
    assert survivors == {fresh.id}


async def test_a_dispatched_outbox_rows_own_shorter_window_is_unaffected_by_the_dead_letter_one(
    db,
):
    """The two cutoffs are independent: a row dispatched a moment ago is still bound by
    TABLES_OUTBOX_RETENTION_DAYS regardless of how generous the undispatched window is."""
    _owner, org, table = await _tenant(db)
    old_but_dispatched = _outbox(
        org,
        table,
        dispatched_age=timedelta(days=settings.TABLES_OUTBOX_RETENTION_DAYS + 1),
        created_age=timedelta(days=settings.TABLES_OUTBOX_RETENTION_DAYS + 1),
    )
    db.add(old_but_dispatched)
    await db.flush()

    (result,) = await _sweep(db)

    assert result.removed == {"table_outbox": 1}
    assert await _count(db, VirtualTableOutbox, org) == 0


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


async def test_an_older_classs_backlog_is_worked_off_in_batches_over_several_sweeps(
    db, monkeypatch
):
    """MAX_BATCHES still bounds an older class across passes; the table classes below get
    their own budget, sized against the write rate rather than this fixed one."""
    owner, org, _table = await _tenant(db)
    org.retention_days = {"workspaces": 1}
    monkeypatch.setattr(retention_module, "BATCH", 2)
    monkeypatch.setattr(retention_module, "MAX_BATCHES", 2)
    remaining = {"n": 5}

    async def delete_up_to_the_batch_size(db, *, organization_id, cutoff, limit):
        took = min(limit, remaining["n"])
        remaining["n"] -= took
        return took

    monkeypatch.setattr(retention_repo, "delete_workspaces", delete_up_to_the_batch_size)

    (first,) = await _sweep(db)
    (second,) = await _sweep(db)

    assert first.removed == {"workspaces": 4}
    assert second.removed == {"workspaces": 1}
    assert owner.id


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
    assert (
        await retention_repo.delete_table_outbox(
            db, **scope, undispatched_cutoff=NOW - timedelta(days=1)
        )
        == 1
    )

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
    # The two rows the first batch removed are part of what commits, so they are reported.
    assert result.removed == {"table_receipts": 2}
    assert await _audited(db, org) == {
        "removed": {"table_receipts": 2},
        "failed": ["table_receipts"],
    }


async def test_a_failing_older_class_reports_the_batches_that_finished_before_it(db, monkeypatch):
    owner, org, _table = await _tenant(db)
    org.retention_days = {"workspaces": 1}
    monkeypatch.setattr(retention_module, "BATCH", 2)
    calls = {"n": 0}

    async def second_batch_fails(db, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return 2
        return await _fail_in_the_database(db)

    monkeypatch.setattr(retention_repo, "delete_workspaces", second_batch_fails)

    (result,) = await _sweep(db)

    assert result.failed == ["workspaces"]
    assert result.removed == {"workspaces": 2}
    assert await _audited(db, org) == {"removed": {"workspaces": 2}, "failed": ["workspaces"]}
    assert owner.id


async def test_a_class_that_removed_nothing_before_failing_is_not_reported_as_removed(
    db, monkeypatch
):
    owner, org, _table = await _tenant(db)
    db.add(_receipt(org, owner, "old", age=timedelta(days=5)))
    await db.flush()
    monkeypatch.setattr(retention_repo, "delete_table_outbox", _fail_in_the_database)

    (result,) = await _sweep(db)

    assert "table_outbox" not in result.removed
    assert (await _audited(db, org))["failed"] == ["table_outbox"]


async def _add_active_member(db, org):
    """One more member whose account can sign in - what the sweep budget scales by."""
    member = await make_user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=org.id, user_id=member.id, role="member"
        )
    )
    await db.flush()
    return member


async def test_a_table_class_drains_a_backlog_bigger_than_the_older_classes_cap_in_one_pass(
    db, monkeypatch
):
    """The old MAX_BATCHES=40 cap at BATCH=2 would be 80 rows; this proves a table class is no
    longer held to that, by draining more than it in one pass at the default write-rate budget.
    """
    owner, org, _table = await _tenant(db)
    monkeypatch.setattr(retention_module, "BATCH", 2)
    over_the_old_cap = 100
    expired = timedelta(hours=settings.TABLES_RECEIPT_TTL_HOURS + 1)
    db.add_all([_receipt(org, owner, f"k{n}", age=expired) for n in range(over_the_old_cap)])
    await db.flush()

    (result,) = await _sweep(db)

    assert result.removed == {"table_receipts": over_the_old_cap}
    assert await _count(db, VirtualTableReceipt, org) == 0


async def test_a_fresh_organization_has_exactly_its_owner_as_an_active_member(db):
    """The common case the old single-member assumption happened to get right."""
    owner, org, _table = await _tenant(db)

    assert await member_repo.count_active_for_org(db, org.id) == 1
    assert owner.id


async def test_a_deactivated_members_membership_does_not_count_toward_the_budget(db):
    owner, org, _table = await _tenant(db)
    deactivated = await _add_active_member(db, org)
    deactivated.is_active = False
    await db.flush()

    assert await member_repo.count_active_for_org(db, org.id) == 1


async def test_an_organizations_active_member_count_reaches_the_sweep_budget(db, monkeypatch):
    """The wiring this round fixes: the sweep must ask for *this* organization's own active
    member count and use it, not assume one member regardless of how many an organization has.
    A single-member organization keeps exactly the old, unaffected behaviour: a remainder.
    """
    monkeypatch.setattr(retention_module, "BATCH", 2)
    monkeypatch.setattr(
        retention_module, "_table_sweep_max_batches", lambda active_members: active_members * 2
    )
    single_owner, single_member_org, _t1 = await _tenant(db, "one-member-org")
    busy_owner, busy_org, _t2 = await _tenant(db, "three-member-org")
    await _add_active_member(db, busy_org)
    await _add_active_member(db, busy_org)
    expired = timedelta(hours=settings.TABLES_RECEIPT_TTL_HOURS + 1)
    db.add_all(
        [_receipt(single_member_org, single_owner, f"s{n}", age=expired) for n in range(5)]
        + [_receipt(busy_org, busy_owner, f"b{n}", age=expired) for n in range(5)]
    )
    await db.flush()

    single_result, busy_result = await _sweep(db)

    # One member: budget is 1 * 2 = 2 batches of 2 rows = 4, one of the five rows survives -
    # unchanged from before this fix, because this organization always had one member.
    assert single_result.removed == {"table_receipts": 4}
    assert await _count(db, VirtualTableReceipt, single_member_org) == 1
    # Three members: budget is 3 * 2 = 6 batches of 2 rows = 12, comfortably draining all five
    # in the same pass - the fix, since the old code would have sized this the same as above.
    assert busy_result.removed == {"table_receipts": 5}
    assert await _count(db, VirtualTableReceipt, busy_org) == 0


async def test_the_member_count_actually_queried_is_what_the_budget_is_sized_by(db, monkeypatch):
    """Pins the wiring itself, independent of the budget formula: patching what
    count_active_for_org answers changes what the sweep asks _table_sweep_max_batches for."""
    owner, org, _table = await _tenant(db)
    seen: list[int] = []
    real_max_batches = retention_module._table_sweep_max_batches

    def spy(active_members):
        seen.append(active_members)
        return real_max_batches(active_members)

    monkeypatch.setattr(retention_module, "_table_sweep_max_batches", spy)
    monkeypatch.setattr(member_repo, "count_active_for_org", AsyncMock(return_value=7))
    db.add(_receipt(org, owner, "k", age=timedelta(hours=settings.TABLES_RECEIPT_TTL_HOURS + 1)))
    await db.flush()

    await _sweep(db)

    assert seen == [7]


async def test_a_backlog_bigger_than_one_days_production_shrinks_rather_than_holds_flat(
    db, monkeypatch
):
    """The point of SWEEP_BACKLOG_HEADROOM: a budget sized to exactly one day's steady-state
    production would remove today's rows and never touch yesterday's - the backlog held flat
    forever. Sized with headroom, the surplus capacity each pass eats into what is left over,
    so a real backlog is gone within a couple of passes even as production continues.
    """
    monkeypatch.setattr(retention_module, "BATCH", 2)
    # A stand-in for "one day's production capacity, doubled by headroom": four rows is what
    # steady-state alone would produce and remove in a day: with headroom, eight rows drain.
    monkeypatch.setattr(retention_module, "_table_sweep_max_batches", lambda active_members: 4)
    owner, org, _table = await _tenant(db)
    expired = timedelta(hours=settings.TABLES_RECEIPT_TTL_HOURS + 1)
    # A pre-existing backlog of ten, as if several days had gone unswept.
    db.add_all([_receipt(org, owner, f"old{n}", age=expired) for n in range(10)])
    await db.flush()

    first = (await _sweep(db))[0]
    # A day passes: four more rows arrive at steady state and expire before the next sweep.
    db.add_all([_receipt(org, owner, f"new{n}", age=expired) for n in range(4)])
    await db.flush()
    second = (await _sweep(db))[0]

    assert first.removed == {"table_receipts": 8}
    assert second.removed == {"table_receipts": 6}  # the 2 left over, plus all 4 new arrivals
    assert await _count(db, VirtualTableReceipt, org) == 0


async def test_a_smaller_table_sweep_budget_leaves_the_remainder_for_the_next_pass(db, monkeypatch):
    """The budget is derived from the write-rate setting; lowering it lowers what one pass
    drains, exactly as MAX_BATCHES already does for the older classes."""
    owner, org, _table = await _tenant(db)
    monkeypatch.setattr(retention_module, "BATCH", 2)
    monkeypatch.setattr(retention_module, "_table_sweep_max_batches", lambda active_members: 2)
    expired = timedelta(hours=settings.TABLES_RECEIPT_TTL_HOURS + 1)
    db.add_all([_receipt(org, owner, f"k{n}", age=expired) for n in range(5)])
    await db.flush()

    (first,) = await _sweep(db)
    (second,) = await _sweep(db)

    assert first.removed == {"table_receipts": 4}
    assert second.removed == {"table_receipts": 1}
    assert await _count(db, VirtualTableReceipt, org) == 0


def test_the_table_sweep_budget_scales_with_the_write_rate_and_member_count(monkeypatch):
    """`limit_table_write` keys the write limit per member, so the budget has to scale with
    how many active members an organization has, not assume exactly one - the bug this fixes."""
    monkeypatch.setattr(settings, "RATE_LIMIT_TABLE_WRITES_PER_MINUTE", 60)
    monkeypatch.setattr(retention_module, "BATCH", 500)
    monkeypatch.setattr(retention_module, "MAX_BATCHES", 40)

    # ceil(60 * 60 * 24 * 1 * SWEEP_BACKLOG_HEADROOM / 500), the headroom doubling one day's
    # steady-state production so a real backlog is worked down and not merely held level.
    assert retention_module._table_sweep_max_batches(1) == 346
    # Three members write three times the volume, and the budget scales with them.
    assert retention_module._table_sweep_max_batches(3) == 1037
    assert (
        retention_module._table_sweep_max_batches(3)
        == retention_module._table_sweep_max_batches(1) * 3 - 1
    )  # ceiling division only rounds the single-member figure up, not the tripled one

    # The multiplier is capped: an organization far past MAX_MEMBERS_FOR_TABLE_SWEEP_BUDGET
    # is budgeted the same as one exactly at the cap, so one outsized organization cannot make
    # its own pass grow without bound.
    at_the_cap = retention_module._table_sweep_max_batches(
        retention_module.MAX_MEMBERS_FOR_TABLE_SWEEP_BUDGET
    )
    far_past_it = retention_module._table_sweep_max_batches(
        retention_module.MAX_MEMBERS_FOR_TABLE_SWEEP_BUDGET * 20
    )
    assert at_the_cap == far_past_it

    monkeypatch.setattr(settings, "RATE_LIMIT_TABLE_WRITES_PER_MINUTE", 1)
    assert retention_module._table_sweep_max_batches(1) == 40  # never below MAX_BATCHES
