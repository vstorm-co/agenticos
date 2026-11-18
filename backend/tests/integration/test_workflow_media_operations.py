"""Paid-media identity and holds are enforced by real PostgreSQL state."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.db.models.workflow_media_operation import WorkflowMediaOperation
from app.db.models.workflow_run import NodeAttempt
from app.repositories import workflow_media_operation as media_repo
from app.repositories import workflow_run as run_repo
from app.services.organization_secret import OrganizationSecretService
from tests.integration.workflow_media_support import seed_media

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_media_reads_and_aggregates_never_cross_the_organization(engine):
    mine, other = await seed_media(engine), await seed_media(engine)
    async with mine.seeded.factory() as db:
        operation = await media_repo.create(db, mine.admission())
        # Log-safe identity: a diagnostic representation must not include the
        # secret pin, request fingerprint or future provider receipt contents.
        assert repr(operation) == f"<WorkflowMediaOperation(id={operation.id}, phase=prepared)>"
        await media_repo.create(db, other.admission())
        assert (
            await media_repo.get(db, operation.id, organization_id=other.seeded.org.id, locked=True)
            is None
        )
        assert (
            await media_repo.current_for_node(
                db, organization_id=other.seeded.org.id, node_run_id=mine.node.id
            )
            is None
        )
        assert (
            await media_repo.get(db, operation.id, organization_id=mine.seeded.org.id) is operation
        )
        assert (
            await media_repo.current_for_node(
                db, organization_id=mine.seeded.org.id, node_run_id=mine.node.id, locked=True
            )
            is operation
        )
        assert await media_repo.outstanding_usd(db, organization_id=mine.seeded.org.id) == Decimal(
            "2"
        )
        assert await media_repo.outstanding_usd(db, organization_id=uuid4()) == 0
        assert await media_repo.held_bytes(db, organization_id=mine.seeded.org.id) == 1024
        assert (
            await media_repo.held_bytes(
                db, organization_id=mine.seeded.org.id, workflow_run_id=other.seeded.run.id
            )
            == 0
        )
        assert (
            await media_repo.held_bytes(
                db, organization_id=mine.seeded.org.id, exclude_operation_id=operation.id
            )
            == 0
        )
        assert await media_repo.workflow_has_unresolved(
            db, organization_id=mine.seeded.org.id, workflow_id=mine.seeded.run.workflow_id
        )
        assert not await media_repo.workflow_has_unresolved(
            db, organization_id=other.seeded.org.id, workflow_id=mine.seeded.run.workflow_id
        )


async def test_simultaneous_admissions_leave_one_current_operation_and_one_hold(engine):
    rows = await seed_media(engine)
    async with rows.seeded.factory() as db:
        second = await run_repo.create_attempt(
            db,
            organization_id=rows.seeded.org.id,
            node_run_id=rows.node.id,
            attempt_no=2,
            idempotency_key=str(uuid4()),
            retry_guarantee="none",
            started_at=datetime.now(UTC),
        )
        await db.commit()
    barrier = asyncio.Barrier(2)

    async def admit(attempt_id):
        async with rows.seeded.factory() as db:
            await barrier.wait()
            try:
                operation = await media_repo.create(
                    db, replace(rows.admission(), attempt_id=attempt_id)
                )
                await db.commit()
                return operation.id
            except IntegrityError:
                await db.rollback()
                return None

    async with asyncio.timeout(10):
        results = await asyncio.gather(admit(rows.attempt.id), admit(second.id))
    assert sum(result is not None for result in results) == 1
    async with rows.seeded.factory() as db:
        operation = await media_repo.current_for_node(
            db, organization_id=rows.seeded.org.id, node_run_id=rows.node.id
        )
        assert operation is not None and operation.id in results
        assert await media_repo.outstanding_usd(db, organization_id=rows.seeded.org.id) == Decimal(
            "2"
        )
        assert await media_repo.held_bytes(db, organization_id=rows.seeded.org.id) == 1024


async def test_lease_resolution_never_releases_unknown_spend_or_hides_unbooked_fees(engine):
    rows = await seed_media(engine)
    async with rows.seeded.factory() as db:
        operation = await media_repo.create(db, rows.admission())
        scope = {"organization_id": rows.seeded.org.id, "workflow_run_id": rows.seeded.run.id}
        assert await media_repo.outstanding_usd(db, **scope, uncovered_only=True) == 0
        await db.execute(
            update(NodeAttempt)
            .where(NodeAttempt.id == rows.attempt.id)
            .values(reserved_usd=Decimal("0.5"))
        )
        assert await media_repo.outstanding_usd(db, **scope, uncovered_only=True) == Decimal("1.5")
        await db.execute(
            update(NodeAttempt).where(NodeAttempt.id == rows.attempt.id).values(status="uncertain")
        )
        assert await media_repo.outstanding_usd(db, **scope, uncovered_only=True) == Decimal("2")
        assert (
            await media_repo.unbooked_for_node(
                db, organization_id=rows.seeded.org.id, node_run_id=rows.node.id
            )
            == []
        )
        await media_repo.change(
            db,
            operation.id,
            organization_id=rows.seeded.org.id,
            values={
                "phase": "unknown",
                "held_usd": Decimal("1.2"),
                "incurred_usd": Decimal("0.8"),
                "cost_source": "catalog_estimate",
            },
        )
        assert await media_repo.outstanding_usd(db, **scope, uncovered_only=True) == Decimal("2")
        assert [
            item.id
            for item in await media_repo.unbooked_for_node(
                db, organization_id=rows.seeded.org.id, node_run_id=rows.node.id
            )
        ] == [operation.id]
        await media_repo.change(
            db,
            operation.id,
            organization_id=rows.seeded.org.id,
            values={"booked_usd": Decimal("0.8")},
        )
        assert await media_repo.outstanding_usd(db, **scope, uncovered_only=True) == Decimal("1.2")


async def test_explicit_replacement_and_key_deletion_preserve_the_previous_unknown_hold(engine):
    rows = await seed_media(engine)
    async with rows.seeded.factory() as db:
        previous = await media_repo.create(db, rows.admission())
        await media_repo.change(
            db,
            previous.id,
            organization_id=rows.seeded.org.id,
            values={
                "phase": "unknown",
                "superseded_at": datetime.now(UTC),
            },
        )
        attempt = await run_repo.create_attempt(
            db,
            organization_id=rows.seeded.org.id,
            node_run_id=rows.node.id,
            attempt_no=2,
            idempotency_key=str(uuid4()),
            retry_guarantee="none",
            started_at=datetime.now(UTC),
        )
        current = await media_repo.create(db, replace(rows.admission(), attempt_id=attempt.id))
        await OrganizationSecretService(db).delete(rows.seeded.ctx, rows.secret_id)
        assert (
            await media_repo.current_for_node(
                db, organization_id=rows.seeded.org.id, node_run_id=rows.node.id
            )
            is current
        )
        assert await media_repo.get(db, previous.id, organization_id=rows.seeded.org.id) is previous
        assert previous.secret_id == rows.secret_id and previous.phase == "unknown"
        assert await media_repo.outstanding_usd(db, organization_id=rows.seeded.org.id) == Decimal(
            "4"
        )
        assert await media_repo.held_bytes(db, organization_id=rows.seeded.org.id) == 2048
        await db.commit()


@pytest.mark.parametrize(
    "column", ["workflow_run_id", "node_run_id", "origin_attempt_id", "collector_attempt_id"]
)
async def test_media_lineage_cannot_reference_another_organization(engine, column):
    rows, other = await seed_media(engine), await seed_media(engine)
    foreign = {
        "workflow_run_id": other.seeded.run.id,
        "node_run_id": other.node.id,
        "origin_attempt_id": other.attempt.id,
        "collector_attempt_id": other.attempt.id,
    }
    async with rows.seeded.factory() as db:
        operation = await media_repo.create(db, rows.admission())
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(
                    update(WorkflowMediaOperation)
                    .where(WorkflowMediaOperation.id == operation.id)
                    .values(**{column: foreign[column]})
                )
                await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await db.refresh(operation)
        assert (
            operation.organization_id == rows.seeded.org.id
            and operation.workflow_run_id == rows.seeded.run.id
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"held_usd": Decimal("NaN")},
        {"held_usd": Decimal("3")},
        {"incurred_usd": Decimal("-1")},
        {"booked_usd": Decimal("1")},
        {"held_bytes": 2048},
        {"request_hash": "bad"},
        {"phase": "stored", "stored_file_id": uuid4()},
        {"accounting_complete": True},
        {"pricing_snapshot": []},
        {"pricing_snapshot": {"unbounded": "x" * 16384}},
        {"cost_evidence": []},
        {"cost_evidence": {"unbounded": "x" * 4096}},
        {"submission_token": uuid4()},
        {"effect_started_at": datetime.now(UTC)},
    ],
)
async def test_database_refuses_invalid_spend_output_and_reservation_states(engine, changes):
    rows = await seed_media(engine)
    async with rows.seeded.factory() as db:
        operation = await media_repo.create(db, rows.admission())
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(
                    update(WorkflowMediaOperation)
                    .where(WorkflowMediaOperation.id == operation.id)
                    .values(**changes)
                )
        assert (
            await db.execute(
                select(WorkflowMediaOperation.held_usd).where(
                    WorkflowMediaOperation.id == operation.id
                )
            )
        ).scalar_one() == Decimal("2")


@pytest.mark.parametrize(
    "changes",
    [{"api_key": "forbidden"}, {"provider": None}, {"model": "other"}, {"kind": None}, {"id": ""}],
)
async def test_receipt_is_closed_and_bound_to_the_original_provider(engine, changes):
    rows = await seed_media(engine)
    async with rows.seeded.factory() as db:
        operation = await media_repo.create(db, rows.admission())
        receipt = {
            "provider": "google",
            "api": "gemini_interactions",
            "model": "synthetic-video",
            "kind": "file",
            "id": "opaque-file",
        }
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await media_repo.change(
                    db,
                    operation.id,
                    organization_id=rows.seeded.org.id,
                    values={
                        "provider_receipt": {**receipt, **changes},
                        "phase": "submitted",
                        "effect_started_at": datetime.now(UTC),
                        "submission_token": operation.collector_token,
                        "submitted_at": datetime.now(UTC),
                    },
                )


async def test_receipt_keeps_original_pricing_and_submission_fence_across_collector_changes(engine):
    rows = await seed_media(engine)
    admitted = rows.admission()
    async with rows.seeded.factory() as db:
        operation = await media_repo.create(db, admitted)
        submitted = datetime.now(UTC)
        receipt = {
            "provider": "google",
            "api": "gemini_interactions",
            "model": "synthetic-video",
            "kind": "file",
            "id": "opaque-file",
        }
        await media_repo.change(
            db,
            operation.id,
            organization_id=rows.seeded.org.id,
            values={
                "phase": "submitted",
                "provider_receipt": receipt,
                "effect_started_at": submitted,
                "submitted_at": submitted,
                "submission_token": admitted.collector_token,
                "collector_token": uuid4(),
                "cost_evidence": {"kind": "video", "seconds": 5},
            },
        )
        await db.commit()
    # A later catalog value is not the historical basis of this accepted job.
    admitted.pricing_snapshot["usd_per_second"] = "99"
    async with rows.seeded.factory() as db:
        loaded = await media_repo.get(db, operation.id, organization_id=rows.seeded.org.id)
        assert loaded is not None
        assert loaded.pricing_snapshot["usd_per_second"] == "0.4"
        assert loaded.submission_token == admitted.collector_token
        assert loaded.collector_token != loaded.submission_token
        assert loaded.provider_receipt == receipt
        assert loaded.cost_evidence == {"kind": "video", "seconds": 5}
