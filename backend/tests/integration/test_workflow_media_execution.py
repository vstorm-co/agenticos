"""Real claims, ledger and file commits around synthetic provider effects."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.secret_kinds import ApiKeySecret
from app.db.locks import LockScope, hold_subject
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import DispatchOutbox, NodeAttempt, WorkflowRun
from app.repositories import workflow_media_operation as media_repo
from app.repositories import workflow_run as run_repo
from app.services.media_inspection import MediaInfo
from app.services.organization_secret import OrganizationSecretService
from app.services.video_generation import Clip, VideoReceipt
from app.services.workflow_execution import context, dispatcher
from app.services.workflow_execution.reconciler import WorkflowReconcilerService
from app.services.workflow_media import _admission, _execution
from app.workflows.contracts.results import Completed, Failed, Uncertain
from tests.integration.workflow_media_runtime_support import (
    image_transport,
    png_bytes,
    seed_generation,
)
from tests.integration.workflow_run_support import settle, start_attempt

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def file_count(rows):
    async with rows.seeded.factory() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(WorkflowFile)
                .where(WorkflowFile.workflow_run_id == rows.seeded.run.id)
            )
        ).scalar_one()


async def test_real_image_sdk_submits_once_after_a_committed_fence_and_books_the_original_attempt(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    data = png_bytes()

    async def before_response(_request):
        operation = await rows.operation()
        assert (
            operation.phase == "submitting"
            and operation.submission_token == rows.begun.dispatch_token
        )
        # The long provider call owns no outbox lock: its real heartbeat can run.
        async with asyncio.timeout(3), rows.seeded.factory() as db:
            assert await run_repo.renew_lease(
                db,
                node_run_id=rows.begun.node_run_id,
                token=rows.begun.dispatch_token,
                lease_seconds=300,
            )
            await db.commit()

    requests = image_transport(monkeypatch, data, before_response=before_response)
    outcome = await dispatcher.call_handler(rows.begun)
    assert isinstance(outcome.result, Completed), outcome.result
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["max_tool_calls"] == 1 and body["max_output_tokens"] == 8192
    assert body["service_tier"] == "default"
    output = outcome.result.output
    assert (output.width, output.height, output.byte_size) == (12, 8, len(data))
    operation = await rows.operation()
    assert operation.phase == "stored" and operation.stored_file_id == output.file.file_id
    assert operation.held_bytes == 0 and operation.held_usd == Decimal("0.64")
    assert operation.incurred_usd > 0 and operation.booked_usd == 0
    assert operation.cost_source == "catalog_estimate" and not operation.accounting_complete
    await settle(rows.seeded, rows.begun, outcome)
    await settle(rows.seeded, rows.begun, outcome)
    async with rows.seeded.factory() as db:
        operation = await media_repo.get(db, operation.id, organization_id=rows.seeded.org.id)
        attempt = await db.get(NodeAttempt, rows.begun.attempt_id)
        run = await db.get(WorkflowRun, rows.seeded.run.id)
        assert operation.booked_usd == operation.incurred_usd == attempt.cost == run.spent_cost
        assert not attempt.cost_is_partial and not run.cost_is_partial
        assert (
            await run_repo.node_spend_since(
                db, organization_id=rows.seeded.org.id, since=run.started_at - timedelta(seconds=1)
            )
            == operation.incurred_usd
        )
    assert await file_count(rows) == 1


async def test_unexpected_reported_image_tier_keeps_the_durable_hold_without_booking_standard_fees(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    requests = image_transport(monkeypatch, png_bytes(), service_tier="priority")
    outcome = await dispatcher.call_handler(rows.begun)
    assert isinstance(outcome.result, Completed), outcome.result
    assert len(requests) == 1 and json.loads(requests[0].content)["service_tier"] == "default"
    await settle(rows.seeded, rows.begun, outcome)
    operation = await rows.operation()
    assert operation.phase == "stored" and operation.held_usd == operation.reserved_usd
    assert operation.incurred_usd == operation.booked_usd == 0
    assert not operation.accounting_complete and operation.cost_evidence["unexpected_service_tier"]
    async with rows.seeded.factory() as db:
        attempt = await db.get(NodeAttempt, rows.begun.attempt_id)
        run = await db.get(WorkflowRun, rows.seeded.run.id)
        assert attempt.cost == run.spent_cost == 0
    assert await file_count(rows) == 1


async def test_concurrent_collectors_publish_one_preassigned_file_and_never_submit_twice(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    requests = image_transport(monkeypatch, png_bytes())
    async with asyncio.timeout(20):
        outcomes = await asyncio.gather(
            dispatcher.call_handler(rows.begun), dispatcher.call_handler(rows.begun)
        )
    assert len(requests) == 1
    assert any(isinstance(outcome.result, Completed) for outcome in outcomes)
    operation = await rows.operation()
    assert operation.phase == "stored" and await file_count(rows) == 1


@pytest.mark.parametrize("failure", ["missing_image", "unusable_bytes", "transport"])
async def test_billed_or_unknown_provider_failure_never_turns_into_a_second_image_request(
    engine, monkeypatch, tmp_path, failure
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)

    async def fail(_request):
        raise RuntimeError("synthetic transport failure containing a private URL and key")

    requests = image_transport(
        monkeypatch,
        b"not an image" if failure == "unusable_bytes" else png_bytes(),
        missing_image=failure == "missing_image",
        before_response=fail if failure == "transport" else None,
    )
    outcome = await dispatcher.call_handler(rows.begun)
    assert not isinstance(outcome.result, Completed) and len(requests) == 1
    operation = await rows.operation()
    assert operation.effect_started_at is not None and operation.held_usd > 0
    if failure != "transport":
        assert operation.incurred_usd > 0
    assert "private URL" not in outcome.result.model_dump_json()
    assert "key" not in outcome.result.model_dump_json()
    assert await file_count(rows) == 0
    again = await dispatcher.call_handler(rows.begun)
    assert not isinstance(again.result, Completed) and len(requests) == 1


@pytest.mark.parametrize(
    "boundary",
    [
        "missing_token",
        "lost_claim",
        "replaced_token",
        "expired_lease",
        "revoked_user",
        "rotated_key",
        "deleted_key",
        "ended_run",
        "deadline",
        "newer_attempt",
    ],
)
async def test_effect_rechecks_current_authority_claim_and_credential_before_spending(
    engine, monkeypatch, tmp_path, boundary
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    requests = image_transport(monkeypatch, png_bytes())
    begun = rows.begun
    if boundary == "missing_token":
        begun = replace(begun, dispatch_context=replace(begun.dispatch_context, claim_token=None))
    elif boundary == "lost_claim":
        begun.dispatch_context.claim.lost = True
    else:
        async with rows.seeded.factory() as db:
            if boundary in {"replaced_token", "expired_lease"}:
                values = (
                    {"claimed_by": uuid4()}
                    if boundary == "replaced_token"
                    else {"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                )
                await db.execute(
                    update(DispatchOutbox)
                    .where(DispatchOutbox.node_run_id == begun.node_run_id)
                    .values(**values)
                )
            elif boundary == "revoked_user":
                await db.execute(
                    update(User).where(User.id == rows.seeded.principal.id).values(is_active=False)
                )
            elif boundary == "deleted_key":
                await db.delete(await db.get(OrganizationSecret, rows.config.secret_id))
            elif boundary == "ended_run":
                await db.execute(
                    update(WorkflowRun)
                    .where(WorkflowRun.id == rows.seeded.run.id)
                    .values(status="cancelled", ended_at=datetime.now(UTC))
                )
            elif boundary == "deadline":
                await db.execute(
                    update(WorkflowRun)
                    .where(WorkflowRun.id == rows.seeded.run.id)
                    .values(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
                )
            elif boundary == "newer_attempt":
                await run_repo.create_attempt(
                    db,
                    organization_id=rows.seeded.org.id,
                    node_run_id=begun.node_run_id,
                    attempt_no=2,
                    idempotency_key=str(uuid4()),
                    retry_guarantee="none",
                    started_at=datetime.now(UTC),
                )
            await db.commit()
        if boundary == "rotated_key":
            with context.dispatching_as(begun.dispatch_context):
                await _admission.admit(rows.config, rows.supplied, reference_sha256=None)
            async with rows.seeded.factory() as db:
                await OrganizationSecretService(db).update(
                    rows.seeded.ctx,
                    rows.config.secret_id,
                    value=ApiKeySecret(api_key="rotated-synthetic-key"),
                )
                await db.commit()
    result = await dispatcher.call_handler(begun)
    assert isinstance(result.result, Failed), result.result
    assert requests == [] and await file_count(rows) == 0


async def test_revocation_during_blob_write_rolls_back_publication_but_preserves_the_fee_and_recoverable_bytes(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    requests = image_transport(monkeypatch, png_bytes())
    original = rows.storage.save_at

    async def save_then_revoke(path, data):
        await original(path, data)
        async with rows.seeded.factory() as db:
            await db.execute(
                update(User).where(User.id == rows.seeded.principal.id).values(is_active=False)
            )
            await db.commit()

    monkeypatch.setattr(rows.storage, "save_at", save_then_revoke)
    result = await dispatcher.call_handler(rows.begun)
    assert isinstance(result.result, Uncertain) and len(requests) == 1
    operation = await rows.operation()
    assert operation.phase == "collecting" and operation.incurred_usd > 0
    assert operation.held_bytes == rows.config.max_output_bytes and await file_count(rows) == 0
    path = f"workflow-files/{operation.organization_id}/{operation.workflow_run_id}/{operation.output_file_id}"
    assert await rows.storage.load(path) == png_bytes()
    async with rows.seeded.factory() as db:
        await db.execute(
            update(User).where(User.id == rows.seeded.principal.id).values(is_active=True)
        )
        await db.commit()
    monkeypatch.setattr(rows.storage, "save_at", original)
    recovered = await dispatcher.call_handler(rows.begun)
    assert isinstance(recovered.result, Completed) and len(requests) == 1
    assert (
        recovered.result.output.file.file_id == operation.output_file_id
        and await file_count(rows) == 1
    )


async def test_cancellation_after_blob_write_retains_one_identity_for_a_no_charge_recovery(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    requests = image_transport(monkeypatch, png_bytes())
    saved, blocked = asyncio.Event(), asyncio.Event()
    original = rows.storage.save_at

    async def pause_after_write(path, data):
        await original(path, data)
        saved.set()
        await blocked.wait()

    monkeypatch.setattr(rows.storage, "save_at", pause_after_write)
    task = asyncio.create_task(dispatcher.call_handler(rows.begun))
    try:
        async with asyncio.timeout(20):
            await saved.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    operation = await rows.operation()
    assert (
        operation.phase == "collecting" and operation.held_bytes > 0 and await file_count(rows) == 0
    )
    monkeypatch.setattr(rows.storage, "save_at", original)
    recovered = await dispatcher.call_handler(rows.begun)
    assert isinstance(recovered.result, Completed) and len(requests) == 1
    assert (
        recovered.result.output.file.file_id == operation.output_file_id
        and await file_count(rows) == 1
    )


@pytest.mark.parametrize("when", ["admission", "after_effect"])
async def test_storage_quota_never_erases_an_incurred_fee(engine, monkeypatch, tmp_path, when):
    rows = await seed_generation(engine, monkeypatch, tmp_path)

    async def reduce_quota(_request):
        monkeypatch.setattr(settings, "WORKFLOW_ORG_MAX_FILE_BYTES", 1)

    requests = image_transport(
        monkeypatch, png_bytes(), before_response=reduce_quota if when == "after_effect" else None
    )
    if when == "admission":
        monkeypatch.setattr(settings, "WORKFLOW_ORG_MAX_FILE_BYTES", 1)
    outcome = await dispatcher.call_handler(rows.begun)
    assert not isinstance(outcome.result, Completed) and await file_count(rows) == 0
    if when == "admission":
        assert requests == [] and await rows.operation() is None
    else:
        operation = await rows.operation()
        assert len(requests) == 1 and operation.incurred_usd > 0 and operation.held_bytes > 0
        await settle(rows.seeded, rows.begun, outcome)
        operation = await rows.operation()
        assert operation.booked_usd == operation.incurred_usd


async def test_lost_video_acknowledgement_resumes_the_same_receipt_and_charges_its_original_attempt(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path, kind="video")
    submissions, collections = [], []
    data = b"synthetic video transport bytes"

    async def provider(entry, **kwargs):
        receipt = kwargs["receipt"]
        if receipt is None:
            submissions.append(1)
            receipt = VideoReceipt(
                provider=entry.provider,
                api=entry.api,
                model=kwargs["model"],
                kind="job",
                id="opaque-synthetic-job",
            )
            await kwargs["on_receipt"](receipt)
            raise RuntimeError("Lost acknowledgement after the durable receipt")
        collections.append(receipt.id)
        return Clip(data=data, seconds=rows.config.requested_seconds())

    monkeypatch.setattr(_execution, "generate_video", provider)
    monkeypatch.setattr(
        _execution,
        "_inspect_output",
        AsyncMock(
            return_value=MediaInfo(
                kind="video",
                media_type="video/mp4",
                byte_size=len(data),
                width=16,
                height=16,
                duration_seconds=rows.config.requested_seconds(),
            )
        ),
    )
    first = await dispatcher.call_handler(rows.begun)
    assert isinstance(first.result, Uncertain)
    operation = await rows.operation()
    assert (
        operation.phase == "submitted"
        and operation.provider_receipt["id"] == "opaque-synthetic-job"
    )
    assert operation.incurred_usd == 0 and operation.held_usd == rows.config.reservation_usd()
    await settle(rows.seeded, rows.begun, first)
    async with rows.seeded.factory() as db:
        await hold_subject(db, LockScope.WORKFLOW_FILE_BYTES, rows.seeded.org.id)
        run = await run_repo.get_run_by_id_for_update(db, rows.seeded.run.id)
        node = await run_repo.get_node_run_by_id_for_update(db, rows.begun.node_run_id)
        latest = await run_repo.get_latest_attempt(db, node_run_id=node.id)
        await dispatcher.resolve_needs_attention(
            db, run=run, node_run=node, latest=latest, choice="run_again", now=datetime.now(UTC)
        )
        await db.commit()
    second = await start_attempt(rows.seeded, rows.begun.node_run_id)
    result = await dispatcher.call_handler(second)
    assert isinstance(result.result, Completed), result.result
    assert submissions == [1] and collections == ["opaque-synthetic-job"]
    await settle(rows.seeded, second, result)
    async with rows.seeded.factory() as db:
        original = await db.get(NodeAttempt, rows.begun.attempt_id)
        collector = await db.get(NodeAttempt, second.attempt_id)
        operation = await media_repo.get(db, operation.id, organization_id=rows.seeded.org.id)
        assert original.cost == operation.incurred_usd == operation.booked_usd > 0
        assert (
            collector.cost == 0 and original.retry_guarantee == collector.retry_guarantee == "none"
        )
        assert operation.accounting_complete and operation.held_usd == operation.held_bytes == 0
    assert await file_count(rows) == 1


async def test_late_fee_sweep_books_once_after_the_attempt_has_already_been_resolved(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    requests = image_transport(monkeypatch, png_bytes())
    result = await dispatcher.call_handler(rows.begun)
    assert isinstance(result.result, Completed) and len(requests) == 1
    async with rows.seeded.factory() as db:
        await db.execute(
            update(NodeAttempt)
            .where(NodeAttempt.id == rows.begun.attempt_id)
            .values(status="uncertain", ended_at=datetime.now(UTC))
        )
        await db.commit()
    async with rows.seeded.factory() as db:
        assert await WorkflowReconcilerService(db).book_pending_media_costs() == 1
        await db.commit()
    async with rows.seeded.factory() as db:
        assert await WorkflowReconcilerService(db).book_pending_media_costs() == 0
        attempt = await db.get(NodeAttempt, rows.begun.attempt_id)
        operation = await media_repo.current_for_node(
            db, organization_id=rows.seeded.org.id, node_run_id=rows.begun.node_run_id
        )
        assert (
            attempt.status == "uncertain"
            and attempt.cost == operation.incurred_usd == operation.booked_usd
        )
