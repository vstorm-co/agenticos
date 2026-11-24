"""Expired claims preserve media evidence and use only canonical recovery paths."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.workflow import Workflow
from app.db.models.workflow_run import DispatchOutbox, NodeAttempt, NodeRun, WorkflowRun
from app.repositories import workflow_media_operation as media_repo
from app.repositories import workflow_run as run_repo
from app.schemas.workflow_media import WorkflowMediaCharged, WorkflowMediaNotCharged
from app.services.media_inspection import MediaInfo
from app.services.video_generation import Clip, VideoReceipt
from app.services.workflow_execution import budget, context, dispatcher
from app.services.workflow_execution.reconciler import WorkflowReconcilerService
from app.services.workflow_media import _execution, _recovery
from app.services.workflow_media._admission import admit
from app.services.workflow_media._errors import MediaOperationError
from app.services.workflow_media._journal import MediaJournal
from app.services.workflow_media_read import WorkflowMediaReadService
from app.services.workflow_media_resolution import WorkflowMediaResolutionService
from app.services.workflow_registry import WorkflowInUseError, WorkflowRegistryService
from app.workflows.contracts.results import Completed
from tests.integration.workflow_media_runtime_support import seed_generation
from tests.integration.workflow_media_support import seed_media
from tests.integration.workflow_run_support import settle, start_attempt

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def expire(rows):
    async with rows.seeded.factory() as db:
        await db.execute(
            update(DispatchOutbox)
            .where(
                DispatchOutbox.node_run_id == rows.begun.node_run_id,
                DispatchOutbox.status == "claimed",
            )
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()


async def prepare(rows, *, submitted=False, receipted=False):
    with context.dispatching_as(rows.begun.dispatch_context):
        operation = await admit(rows.config, rows.supplied, reference_sha256=None)
    journal = MediaJournal(operation)
    if submitted:
        await journal.start(rows.begun.dispatch_context)
    if receipted:
        await journal.receipt(
            VideoReceipt(
                provider=operation.provider,
                api=operation.provider_api,
                model=operation.model,
                kind="job",
                id="recover-only-job",
            )
        )
    return journal


@pytest.mark.parametrize("at_ceiling", [False, True])
async def test_orphaned_receipt_uses_existing_retry_backoff_and_ceiling_without_weakening_none_guarantee(
    engine, monkeypatch, tmp_path, at_ceiling
):
    rows = await seed_generation(engine, monkeypatch, tmp_path, kind="video")
    monkeypatch.setattr(settings, "WORKFLOW_RETRY_CEILING", 1 if at_ceiling else 3)
    await prepare(rows, submitted=True, receipted=True)
    await expire(rows)
    async with rows.seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
        await db.commit()
    async with rows.seeded.factory() as db:
        attempt = await db.get(NodeAttempt, rows.begun.attempt_id)
        run = await db.get(WorkflowRun, rows.seeded.run.id)
        pending = list(
            (
                await db.scalars(
                    select(DispatchOutbox).where(
                        DispatchOutbox.node_run_id == rows.begun.node_run_id,
                        DispatchOutbox.status == "pending",
                    )
                )
            ).all()
        )
        assert attempt.status == "uncertain" and attempt.retry_guarantee == "none"
        if at_ceiling:
            assert (
                run.status == "failed"
                and run.error["code"] == "ATTEMPTS_INTERRUPTED"
                and not pending
            )
        else:
            assert len(pending) == 1 and pending[0].available_at > attempt.ended_at
            assert run.ended_at is None
        operation = await rows.operation()
        assert operation.phase == "submitted" and operation.held_usd == operation.reserved_usd


async def test_known_receipt_can_be_collected_at_a_spent_run_cap_without_new_reservation_or_post(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path, kind="video")
    await prepare(rows, submitted=True, receipted=True)
    await expire(rows)
    async with rows.seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
        await db.execute(
            update(DispatchOutbox)
            .where(
                DispatchOutbox.node_run_id == rows.begun.node_run_id,
                DispatchOutbox.status == "pending",
            )
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == rows.seeded.run.id)
            .values(spent_cost=Decimal("20"))
        )
        await db.commit()
    next_attempt = await start_attempt(rows.seeded, rows.begun.node_run_id)
    async with rows.seeded.factory() as db:
        attempt = await db.get(NodeAttempt, next_attempt.attempt_id)
        assert attempt.reserved_usd is None and attempt.retry_guarantee == "none"
    calls = []
    data = b"synthetic collected video"

    async def collect(_provider, **kwargs):
        assert kwargs["receipt"].id == "recover-only-job"
        assert kwargs["protected_downloads"] is True
        calls.append(kwargs["receipt"].id)
        return Clip(data=data, seconds=rows.config.requested_seconds())

    monkeypatch.setattr(_execution, "generate_video", collect)
    monkeypatch.setattr(
        _execution,
        "_inspect_output",
        AsyncMock(
            return_value=MediaInfo(
                kind="video",
                media_type="video/mp4",
                byte_size=len(data),
                duration_seconds=rows.config.requested_seconds(),
            )
        ),
    )
    outcome = await dispatcher.call_handler(next_attempt)
    assert isinstance(outcome.result, Completed), outcome.result
    await settle(rows.seeded, next_attempt, outcome)
    assert calls == ["recover-only-job"]
    operation = await rows.operation()
    assert operation.origin_attempt_id == rows.begun.attempt_id
    assert operation.collector_attempt_id == next_attempt.attempt_id
    assert operation.phase == "stored" and operation.booked_usd == operation.incurred_usd > 0


@pytest.mark.parametrize("submitted", [False, True])
async def test_orphan_without_receipt_never_requeues_a_paid_submission_and_only_unsubmitted_work_releases_its_hold(
    engine, monkeypatch, tmp_path, submitted
):
    rows = await seed_generation(engine, monkeypatch, tmp_path, kind="video")
    await prepare(rows, submitted=submitted)
    await expire(rows)
    async with rows.seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
        await db.commit()
    operation = await rows.operation()
    assert operation.phase == ("unknown" if submitted else "failed")
    assert operation.held_usd == (operation.reserved_usd if submitted else 0)
    assert operation.held_bytes == (operation.reserved_bytes if submitted else 0)
    async with rows.seeded.factory() as db:
        node = await db.get(NodeRun, rows.begun.node_run_id)
        assert node.status == "needs_attention"
        assert not list(
            (
                await db.scalars(
                    select(DispatchOutbox).where(
                        DispatchOutbox.node_run_id == node.id, DispatchOutbox.status == "pending"
                    )
                )
            ).all()
        )
        if submitted:
            # A repeated orphan observation must not release or requeue unknown work.
            attempt = await db.get(NodeAttempt, rows.begun.attempt_id)
            assert await _recovery.orphaned(db, attempt) is False
            unchanged = await rows.operation()
            assert unchanged.phase == "unknown" and unchanged.held_usd == operation.held_usd
            with pytest.raises(MediaOperationError) as refusal:
                await _recovery.explicit_retry(
                    db,
                    organization_id=rows.seeded.org.id,
                    node_run_id=node.id,
                    now=datetime.now(UTC),
                )
            assert refusal.value.code == "MEDIA_RECONCILIATION_REQUIRED"
        else:
            await _recovery.explicit_retry(
                db, organization_id=rows.seeded.org.id, node_run_id=node.id, now=datetime.now(UTC)
            )
            await db.commit()
            assert (
                await media_repo.current_for_node(
                    db, organization_id=rows.seeded.org.id, node_run_id=node.id
                )
                is None
            )


async def test_read_page_is_tenant_and_run_scoped_and_includes_every_superseded_hold(engine):
    rows, other = await seed_media(engine), await seed_media(engine)
    async with rows.seeded.factory() as db:
        previous = await media_repo.create(db, rows.admission())
        await media_repo.change(
            db,
            previous.id,
            organization_id=rows.seeded.org.id,
            values={
                "phase": "unknown",
                "superseded_at": datetime.now(UTC),
                "incurred_usd": Decimal("0.4"),
                "booked_usd": Decimal("0.1"),
                "cost_source": "catalog_estimate",
            },
        )
        later = await run_repo.create_attempt(
            db,
            organization_id=rows.seeded.org.id,
            node_run_id=rows.node.id,
            attempt_no=2,
            idempotency_key=str(uuid4()),
            retry_guarantee="none",
            started_at=datetime.now(UTC),
        )
        latest = await media_repo.create(db, replace(rows.admission(), attempt_id=later.id))
        await media_repo.change(
            db,
            latest.id,
            organization_id=rows.seeded.org.id,
            values={"incurred_usd": Decimal("0.2"), "cost_source": "reported"},
        )
        await media_repo.create(db, other.admission())
        service = WorkflowMediaReadService(db)
        scope = {"organization_id": rows.seeded.org.id, "workflow_run_id": rows.seeded.run.id}
        assert await service.for_nodes(**scope, node_run_ids=[]) == {}
        projection = await service.for_nodes(**scope, node_run_ids=[rows.node.id, other.node.id])
        assert set(projection) == {rows.node.id}
        read = projection[rows.node.id]
        assert read.operation_id == latest.id and read.node_unresolved_usd == Decimal("4.5")
        assert read.incurred_usd == Decimal("0.2") and read.cost_source == "reported"
        assert (
            await service.for_nodes(
                organization_id=other.seeded.org.id,
                workflow_run_id=rows.seeded.run.id,
                node_run_ids=[rows.node.id],
            )
            == {}
        )
        assert (
            await service.for_nodes(
                organization_id=rows.seeded.org.id,
                workflow_run_id=other.seeded.run.id,
                node_run_ids=[rows.node.id],
            )
            == {}
        )
        assert (
            "secret" not in read.model_dump_json() and "request_hash" not in read.model_dump_json()
        )


async def test_unreserved_budget_retains_media_cost_after_the_lease_and_attempt_end(engine):
    rows = await seed_media(engine)
    async with rows.seeded.factory() as db:
        operation = await media_repo.create(db, rows.admission())
        run = await db.get(WorkflowRun, rows.seeded.run.id)
        # The in-flight attempt already covers this operation's two-dollar hold.
        assert await budget.unreserved(db, run) == Decimal("8")
        await db.execute(
            update(NodeAttempt)
            .where(NodeAttempt.id == rows.attempt.id)
            .values(status="uncertain", ended_at=datetime.now(UTC))
        )
        assert await budget.unreserved(db, run) == Decimal("8")
        await media_repo.change(
            db,
            operation.id,
            organization_id=rows.seeded.org.id,
            values={"incurred_usd": Decimal("0.4"), "cost_source": "catalog_estimate"},
        )
        assert await budget.unreserved(db, run) == Decimal("7.6")


@pytest.mark.parametrize("unresolved", ["spend_hold", "byte_hold", "unbooked_fee"])
async def test_retention_and_workflow_deletion_preserve_unresolved_media_evidence(
    engine, unresolved
):
    rows = await seed_media(engine)
    now = datetime.now(UTC)
    async with rows.seeded.factory() as db:
        operation = await media_repo.create(db, rows.admission())
        await media_repo.change(
            db,
            operation.id,
            organization_id=rows.seeded.org.id,
            values={
                "phase": "failed",
                "held_usd": Decimal("1") if unresolved == "spend_hold" else Decimal(0),
                "held_bytes": 1 if unresolved == "byte_hold" else 0,
                "incurred_usd": Decimal("0.4") if unresolved == "unbooked_fee" else Decimal(0),
                "cost_source": "catalog_estimate",
            },
        )
        await db.execute(
            update(NodeAttempt)
            .where(NodeAttempt.id == rows.attempt.id)
            .values(status="uncertain", ended_at=now)
        )
        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == rows.seeded.run.id)
            .values(status="failed", ended_at=now - timedelta(days=5))
        )
        await db.execute(
            update(Workflow)
            .where(Workflow.id == rows.seeded.run.workflow_id)
            .values(settings={"run_retention_days": 1})
        )
        await db.commit()
    async with rows.seeded.factory() as db:
        assert await run_repo.take_expired_runs(db, now=now, limit=100) == []
        with pytest.raises(WorkflowInUseError, match="unresolved media operations") as refused:
            await WorkflowRegistryService(db).delete(rows.seeded.ctx, rows.seeded.run.workflow_id)
        assert refused.value.code == "WORKFLOW_IN_USE"
        await db.rollback()
    async with rows.seeded.factory() as db:
        current = await media_repo.get(db, operation.id, organization_id=rows.seeded.org.id)
        assert current is not None
        await media_repo.change(
            db,
            current.id,
            organization_id=rows.seeded.org.id,
            values={
                "held_usd": Decimal(0),
                "held_bytes": 0,
                "booked_usd": current.incurred_usd,
                "accounting_complete": True,
            },
        )
        assert await run_repo.take_expired_runs(db, now=now, limit=100) == [
            (rows.seeded.run.id, [])
        ]
        await db.commit()


@pytest.mark.parametrize("charged", [None, Decimal("0.7")])
async def test_a_member_resolved_unknown_hold_leaves_outstanding_usd_and_books_a_reported_charge_once(
    engine, monkeypatch, tmp_path, charged
):
    rows = await seed_generation(engine, monkeypatch, tmp_path, kind="video")
    await prepare(rows, submitted=True)
    await expire(rows)
    async with rows.seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
        await db.commit()
    operation = await rows.operation()
    org_id = rows.seeded.org.id
    assert operation.phase == "unknown"
    async with rows.seeded.factory() as db:
        assert (
            await media_repo.outstanding_usd(db, organization_id=org_id) == operation.reserved_usd
        )
    ctx = AuthContext(user_id=rows.seeded.principal.id, organization_id=org_id, role="owner")
    body = (
        WorkflowMediaNotCharged(outcome="not_charged")
        if charged is None
        else WorkflowMediaCharged(outcome="charged", charged_usd=charged)
    )
    async with rows.seeded.factory() as db:
        read = await WorkflowMediaResolutionService(db).resolve(ctx, operation.id, body)
        await db.commit()
    assert read.phase == "failed" and read.held_usd == 0
    assert read.retry_effect == "new_billable_submission"
    resolved = await rows.operation()
    assert resolved.accounting_complete and resolved.held_bytes == 0
    assert resolved.incurred_usd == (charged or 0)
    async with rows.seeded.factory() as db:
        # Only a reported charge remains, as an incurred fee awaiting the ledger.
        assert await media_repo.outstanding_usd(db, organization_id=org_id) == (charged or 0)
        entry = (
            await db.execute(
                select(AppAdminAuditLog).where(
                    AppAdminAuditLog.action == "workflow_media.hold_resolved"
                )
            )
        ).scalar_one()
        assert entry.organization_id == org_id
        assert entry.actor_user_id == rows.seeded.principal.id
        assert entry.target_id == str(operation.id)
        assert entry.details["outcome"] == body.outcome
        assert entry.details["released_usd"] == str(operation.reserved_usd)
        with pytest.raises(ConflictError):
            await WorkflowMediaResolutionService(db).resolve(ctx, operation.id, body)
    async with rows.seeded.factory() as db:
        assert await WorkflowReconcilerService(db).book_pending_media_costs() == (
            0 if charged is None else 1
        )
        await db.commit()
    async with rows.seeded.factory() as db:
        assert await media_repo.outstanding_usd(db, organization_id=org_id) == 0
        run = await db.get(WorkflowRun, rows.seeded.run.id)
        assert run.spent_cost == (charged or 0)
        # A resolved hold no longer blocks the explicit, separately billed retry.
        await _recovery.explicit_retry(
            db, organization_id=org_id, node_run_id=rows.begun.node_run_id, now=datetime.now(UTC)
        )


async def test_resolving_a_media_hold_is_organization_scoped_and_refuses_a_lower_charge(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path, kind="video")
    await prepare(rows, submitted=True)
    await expire(rows)
    async with rows.seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
        await db.commit()
    operation = await rows.operation()
    async with rows.seeded.factory() as db:
        await media_repo.change(
            db,
            operation.id,
            organization_id=rows.seeded.org.id,
            values={"incurred_usd": Decimal("0.4"), "cost_source": "catalog_estimate"},
        )
        await db.commit()
    stranger = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    member = AuthContext(
        user_id=rows.seeded.principal.id, organization_id=rows.seeded.org.id, role="owner"
    )
    async with rows.seeded.factory() as db:
        service = WorkflowMediaResolutionService(db)
        with pytest.raises(NotFoundError):
            await service.resolve(
                stranger, operation.id, WorkflowMediaNotCharged(outcome="not_charged")
            )
        with pytest.raises(ConflictError, match="below the fee"):
            await service.resolve(
                member,
                operation.id,
                WorkflowMediaCharged(outcome="charged", charged_usd=Decimal("0.1")),
            )
        with pytest.raises(ConflictError, match="resolve it as charged"):
            await service.resolve(
                member, operation.id, WorkflowMediaNotCharged(outcome="not_charged")
            )
    unchanged = await rows.operation()
    assert unchanged.phase == "unknown" and unchanged.held_usd == unchanged.reserved_usd
