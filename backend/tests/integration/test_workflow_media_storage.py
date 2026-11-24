"""Reserved outputs keep exact identity and authority through storage and commit."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.core.secret_kinds import ApiKeySecret
from app.db.models.organization import Organization
from app.db.models.workflow_file import WorkflowFile
from app.repositories import workflow_file as file_repo
from app.repositories import workflow_media_operation as media_repo
from app.services.media_inspection import MediaInfo
from app.services.organization_secret import OrganizationSecretService
from app.services.workflow_execution import context, dispatcher
from app.services.workflow_media import _admission, _execution, _output
from app.services.workflow_media._admission import admit
from app.services.workflow_media._errors import MediaOperationError
from app.services.workflow_media._journal import MediaJournal
from app.workflows import files
from app.workflows.contracts.results import Completed, Failed, Uncertain
from tests.integration.workflow_media_runtime_support import (
    image_transport,
    png_bytes,
    seed_generation,
)
from tests.integration.workflow_run_support import settle

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def output_ready(rows):
    with context.dispatching_as(rows.begun.dispatch_context):
        operation = await admit(rows.config, rows.supplied, reference_sha256=None)
    journal = MediaJournal(operation)
    await journal.start(rows.begun.dispatch_context)
    data = png_bytes()
    operation = await journal.output(
        data,
        MediaInfo(kind="image", media_type="image/png", byte_size=len(data), width=12, height=8),
    )
    return operation, journal, data


@pytest.mark.parametrize(
    "boundary",
    [
        "missing",
        "organization",
        "run",
        "node",
        "superseded",
        "phase",
        "lost_claim",
        "missing_token",
        "changed_token",
        "attempt",
        "digest",
        "metadata",
        "existing_identity",
    ],
)
async def test_reserved_file_refuses_another_identity_or_unverified_bytes_before_storage(
    engine, monkeypatch, tmp_path, boundary
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    operation, _journal, data = await output_ready(rows)
    current = rows.begun.dispatch_context
    operation_id = operation.id
    if boundary == "missing":
        operation_id = uuid4()
    if boundary == "organization":
        current = replace(current, organization_id=uuid4())
    if boundary == "run":
        current = replace(current, workflow_run_id=uuid4())
    if boundary == "node":
        current = replace(current, node_run_id=uuid4())
    if boundary == "lost_claim":
        current.claim.lost = True
    if boundary == "missing_token":
        current = replace(current, claim_token=None)
    if boundary == "changed_token":
        current = replace(current, claim_token=uuid4())
    if boundary == "attempt":
        current = replace(current, attempt_no=current.attempt_no + 1)
    if boundary == "digest":
        data = bytes([data[0] ^ 1]) + data[1:]
    path = f"workflow-files/{operation.organization_id}/{operation.workflow_run_id}/{operation.output_file_id}"
    async with rows.seeded.factory() as db:
        if boundary == "superseded":
            await media_repo.change(
                db,
                operation.id,
                organization_id=operation.organization_id,
                values={"superseded_at": datetime.now(UTC)},
            )
        if boundary == "phase":
            await media_repo.change(
                db,
                operation.id,
                organization_id=operation.organization_id,
                values={"phase": "failed"},
            )
        if boundary == "metadata":
            await media_repo.change(
                db,
                operation.id,
                organization_id=operation.organization_id,
                values={
                    "output_metadata": {**operation.output_metadata, "byte_size": len(data) + 1}
                },
            )
        if boundary == "existing_identity":
            await file_repo.create(
                db,
                file_id=operation.output_file_id,
                organization_id=operation.organization_id,
                workflow_run_id=operation.workflow_run_id,
                producing_node_run_id=operation.node_run_id,
                storage_path=path,
                content_type="image/png",
                byte_size=len(data),
                filename="different.png",
            )
        await db.commit()
    write = AsyncMock(wraps=rows.storage.save_at)
    monkeypatch.setattr(rows.storage, "save_at", write)
    async with rows.seeded.factory() as db:
        with context.dispatching_as(current), pytest.raises(files.ReservedFileError):
            await files.persist_reserved(db, operation_id=operation_id, data=data)
        await db.rollback()
        count = (
            await db.execute(
                select(func.count())
                .select_from(WorkflowFile)
                .where(WorkflowFile.workflow_run_id == rows.seeded.run.id)
            )
        ).scalar_one()
        assert count == int(boundary == "existing_identity")
    write.assert_not_awaited()


async def test_a_second_stored_result_recovers_the_same_file_without_rewriting_or_charging_again(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    requests = image_transport(monkeypatch, png_bytes())
    first = await dispatcher.call_handler(rows.begun)
    assert isinstance(first.result, Completed), first.result
    operation = await rows.operation()
    before = (operation.incurred_usd, operation.held_usd, operation.output_sha256)
    write = AsyncMock(side_effect=AssertionError("The committed file must not be rewritten"))
    monkeypatch.setattr(rows.storage, "save_at", write)
    second = await dispatcher.call_handler(rows.begun)
    assert isinstance(second.result, Completed), second.result
    assert first.result.output.file == second.result.output.file and len(requests) == 1
    after = await rows.operation()
    assert before == (after.incurred_usd, after.held_usd, after.output_sha256)
    journal = MediaJournal(after)
    await journal.interrupted(reason="STALE_COLLECTOR")
    await journal.reject_output(reason="STALE_REJECTION")
    assert (await rows.operation()).phase == "stored"
    write.assert_not_awaited()


async def test_key_rotation_after_the_provider_effect_refuses_publication_and_retains_its_fee(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    requests = image_transport(monkeypatch, png_bytes())
    inspect = _execution._inspect_output

    async def inspect_then_rotate(config, data, media_type):
        metadata = await inspect(config, data, media_type)
        async with rows.seeded.factory() as db:
            await OrganizationSecretService(db).update(
                rows.seeded.ctx,
                rows.config.secret_id,
                value=ApiKeySecret(api_key="rotated-synthetic-key"),
            )
            await db.commit()
        return metadata

    monkeypatch.setattr(_execution, "_inspect_output", inspect_then_rotate)
    result = await dispatcher.call_handler(rows.begun)
    assert isinstance(result.result, Uncertain), result.result
    operation = await rows.operation()
    assert operation.phase == "collecting" and operation.stored_file_id is None
    assert operation.incurred_usd > 0 and operation.held_bytes == rows.config.max_output_bytes
    again = await dispatcher.call_handler(rows.begun)
    assert isinstance(again.result, Failed) and again.result.error.code == "MEDIA_OPERATION_CHANGED"
    assert len(requests) == 1
    await settle(rows.seeded, rows.begun, result)
    assert (await rows.operation()).booked_usd == operation.incurred_usd
    async with rows.seeded.factory() as db:
        assert (
            await db.execute(
                select(func.count())
                .select_from(WorkflowFile)
                .where(WorkflowFile.workflow_run_id == rows.seeded.run.id)
            )
        ).scalar_one() == 0


@pytest.mark.parametrize(
    "boundary", ["node_cap", "organization_cap", "sufficient_organization_cap"]
)
async def test_a_fresh_request_reserves_only_within_current_node_and_organization_caps(
    engine, monkeypatch, tmp_path, boundary
):
    rows = await seed_generation(
        engine, monkeypatch, tmp_path, **({"max_cost_usd": 0.001} if boundary == "node_cap" else {})
    )
    if boundary != "node_cap":
        async with rows.seeded.factory() as db:
            await db.execute(
                update(Organization)
                .where(Organization.id == rows.seeded.org.id)
                .values(
                    monthly_budget_usd=Decimal("100")
                    if boundary == "sufficient_organization_cap"
                    else Decimal("0.001")
                )
            )
            await db.commit()
    requests = image_transport(monkeypatch, png_bytes())
    result = await dispatcher.call_handler(rows.begun)
    if boundary == "sufficient_organization_cap":
        assert isinstance(result.result, Completed), result.result
        assert len(requests) == 1
    else:
        assert isinstance(result.result, Failed), result.result
        expected = (
            "MEDIA_BUDGET_INSUFFICIENT"
            if boundary == "node_cap"
            else "MEDIA_ORGANIZATION_BUDGET_INSUFFICIENT"
        )
        assert result.result.error.code == expected
        assert requests == [] and await rows.operation() is None


async def test_rotation_between_admission_and_effect_refuses_the_original_key_before_submission(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    with context.dispatching_as(rows.begun.dispatch_context):
        operation = await admit(rows.config, rows.supplied, reference_sha256=None)
    async with rows.seeded.factory() as db:
        await OrganizationSecretService(db).update(
            rows.seeded.ctx,
            rows.config.secret_id,
            value=ApiKeySecret(api_key="replacement-synthetic-key"),
        )
        await db.commit()
    requests = image_transport(monkeypatch, png_bytes())
    with (
        context.dispatching_as(rows.begun.dispatch_context),
        pytest.raises(MediaOperationError) as refused,
    ):
        await _admission.recheck(operation, rows.config)
    assert refused.value.code == "MEDIA_CREDENTIAL_CHANGED"
    result = await dispatcher.call_handler(rows.begun)
    assert isinstance(result.result, Failed) and requests == []
    await settle(rows.seeded, rows.begun, result)
    after = await rows.operation()
    assert after.phase == "failed" and after.held_usd == after.held_bytes == 0
    assert after.submission_token is None


async def test_an_incomplete_submission_fact_cannot_publish_an_otherwise_verified_file(
    engine, monkeypatch, tmp_path
):
    rows = await seed_generation(engine, monkeypatch, tmp_path)
    operation, _journal, data = await output_ready(rows)
    async with rows.seeded.factory() as db:
        await media_repo.change(
            db,
            operation.id,
            organization_id=operation.organization_id,
            values={"submitted_at": None},
        )
        await db.commit()
    operation = await rows.operation()
    with (
        context.dispatching_as(rows.begun.dispatch_context),
        pytest.raises(MediaOperationError) as refused,
    ):
        await _output.persist(operation, rows.config, data)
    assert refused.value.code == "MEDIA_JOURNAL_MISMATCH"
    after = await rows.operation()
    assert after.phase == "collecting" and after.stored_file_id is None
    assert after.held_bytes == operation.held_bytes
    async with rows.seeded.factory() as db:
        assert (
            await db.execute(
                select(func.count())
                .select_from(WorkflowFile)
                .where(WorkflowFile.workflow_run_id == rows.seeded.run.id)
            )
        ).scalar_one() == 0
