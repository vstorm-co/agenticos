"""A durable provider fact cannot be reassigned, replaced or charged twice."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.db.models.workflow_media_operation import WorkflowMediaOperation
from app.repositories import workflow_media_operation as media_repo
from app.repositories import workflow_run as run_repo
from app.services.media_inspection import MediaInfo
from app.services.video_generation import VideoReceipt
from app.services.workflow_execution import context
from app.services.workflow_media._admission import admit
from app.services.workflow_media._errors import MediaOperationError
from app.services.workflow_media._journal import MediaJournal, collectable
from app.services.workflow_media._pricing import CostFact, ImageCostEvidence, VideoCostEvidence
from tests.integration.workflow_media_runtime_support import seed_generation

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def prepared(engine, monkeypatch, tmp_path, *, kind="video"):
    rows = await seed_generation(engine, monkeypatch, tmp_path, kind=kind)
    with context.dispatching_as(rows.begun.dispatch_context):
        operation = await admit(rows.config, rows.supplied, reference_sha256=None)
    return rows, operation, MediaJournal(operation)


def receipt(operation, **changes):
    return VideoReceipt.model_validate(
        {
            "provider": operation.provider,
            "api": operation.provider_api,
            "model": operation.model,
            "kind": "job",
            "id": "opaque-job",
            **changes,
        }
    )


async def test_simultaneous_submission_claims_have_exactly_one_winner(
    engine, monkeypatch, tmp_path
):
    rows, operation, first = await prepared(engine, monkeypatch, tmp_path)
    second = MediaJournal(operation)
    results = await asyncio.gather(
        first.start(rows.begun.dispatch_context),
        second.start(rows.begun.dispatch_context),
        return_exceptions=True,
    )
    assert sum(isinstance(result, WorkflowMediaOperation) for result in results) == 1
    assert sum(isinstance(result, MediaOperationError) for result in results) == 1
    latest = await first.read()
    assert latest.phase == "submitting" and latest.submission_token == rows.begun.dispatch_token
    assert (
        latest.collector_token == latest.submission_token and latest.effect_started_at is not None
    )


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "organization_id",
        "workflow_run_id",
        "node_run_id",
        "origin_attempt_id",
        "request_hash",
    ],
)
async def test_journal_cannot_be_redirected_to_another_identity(
    engine, monkeypatch, tmp_path, field
):
    rows, operation, journal = await prepared(engine, monkeypatch, tmp_path)
    await journal.start(rows.begun.dispatch_context)
    setattr(journal, field, "b" * 64 if field == "request_hash" else uuid4())
    with pytest.raises(MediaOperationError, match="identity changed"):
        await journal.receipt(receipt(operation))
    assert (await rows.operation()).provider_receipt is None


async def test_receipts_require_the_original_submission_and_exact_provider_model_identity(
    engine, monkeypatch, tmp_path
):
    rows, operation, journal = await prepared(engine, monkeypatch, tmp_path)
    with pytest.raises(MediaOperationError, match="identity changed"):
        await journal.receipt(receipt(operation))
    await journal.start(rows.begun.dispatch_context)
    for changed in (
        {"provider": "google"},
        {"api": "gemini_interactions"},
        {"model": "other-model"},
    ):
        with pytest.raises(MediaOperationError, match="does not match"):
            await journal.receipt(receipt(operation, **changed))
    valid = receipt(operation)
    await journal.receipt(valid)
    first_time = (await journal.read()).submitted_at
    await journal.receipt(valid)
    assert (await journal.read()).submitted_at == first_time
    with pytest.raises(MediaOperationError, match="different receipt"):
        await journal.receipt(receipt(operation, id="replacement-job"))
    async with rows.seeded.factory() as db:
        await db.execute(
            update(WorkflowMediaOperation)
            .where(WorkflowMediaOperation.id == operation.id)
            .values(submission_token=uuid4())
        )
        await db.commit()
    with pytest.raises(MediaOperationError, match="identity changed"):
        await journal.receipt(valid)


async def test_late_weaker_cost_evidence_does_not_relabel_or_reopen_the_retained_fee(
    engine, monkeypatch, tmp_path
):
    rows, operation, journal = await prepared(engine, monkeypatch, tmp_path)
    await journal.start(rows.begun.dispatch_context)
    maximum = operation.reserved_usd
    known = maximum / 2
    initial = CostFact(
        incurred_usd=known,
        held_usd=maximum / 2,
        source="catalog_estimate",
        complete=False,
        evidence=VideoCostEvidence(seconds=2),
    )
    await journal.cost(initial)
    await journal.cost(
        CostFact(
            incurred_usd=known / 2,
            held_usd=0,
            source="reported",
            complete=True,
            evidence=VideoCostEvidence(seconds=1),
        )
    )
    row = await journal.read()
    assert row.incurred_usd == known and row.cost_source == "catalog_estimate"
    assert row.cost_evidence["seconds"] == "2" and row.held_usd == 0 and row.accounting_complete
    await journal.cost(initial)
    row = await journal.read()
    assert row.held_usd == 0 and row.accounting_complete and row.cost_evidence["seconds"] == "2"
    with pytest.raises(MediaOperationError, match="admitted basis"):
        await journal.cost(initial.model_copy(update={"held_usd": maximum + 1}))
    with pytest.raises(MediaOperationError, match="admitted basis"):
        await journal.cost(
            CostFact(
                incurred_usd=0,
                held_usd=0,
                source="reported",
                complete=True,
                evidence=ImageCostEvidence(
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    caller_priced=True,
                    image_returned=False,
                ),
            )
        )


async def test_newer_attempt_cannot_reuse_the_original_prepared_submission_claim(
    engine, monkeypatch, tmp_path
):
    rows, _operation, journal = await prepared(engine, monkeypatch, tmp_path)
    async with rows.seeded.factory() as db:
        await run_repo.create_attempt(
            db,
            organization_id=rows.seeded.org.id,
            node_run_id=rows.begun.node_run_id,
            attempt_no=2,
            idempotency_key=str(uuid4()),
            retry_guarantee="none",
            started_at=datetime.now(UTC),
        )
        await db.commit()
    with pytest.raises(MediaOperationError, match="cannot submit again"):
        await journal.start(rows.begun.dispatch_context)
    assert (await journal.read()).phase == "prepared"


@pytest.mark.parametrize(
    "evidence", ["prepared", "submitting", "receipt", "output", "failed", "cancelled"]
)
async def test_interruption_releases_only_proven_unsubmitted_work(
    engine, monkeypatch, tmp_path, evidence
):
    rows, operation, journal = await prepared(engine, monkeypatch, tmp_path)
    if evidence != "prepared":
        await journal.start(rows.begun.dispatch_context)
    if evidence in {"receipt", "failed", "cancelled"}:
        await journal.receipt(receipt(operation))
    if evidence == "output":
        await journal.output(
            b"clip",
            MediaInfo(kind="video", media_type="video/mp4", byte_size=4, duration_seconds=1),
        )
    if evidence in {"failed", "cancelled"}:
        async with rows.seeded.factory() as db:
            await media_repo.change(
                db,
                operation.id,
                organization_id=operation.organization_id,
                values={"phase": evidence},
            )
            await db.commit()
    await journal.interrupted(reason="SYNTHETIC_INTERRUPTION")
    current = await journal.read()
    if evidence == "prepared":
        assert (
            current.phase == "failed"
            and current.held_usd == current.held_bytes == 0
            and current.accounting_complete
        )
    else:
        assert (
            current.held_usd == operation.reserved_usd
            and current.held_bytes == operation.reserved_bytes
        )
        expected = {
            "submitting": "unknown",
            "receipt": "submitted",
            "output": "collecting",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        assert current.phase == expected[evidence]
    assert collectable(current) is (evidence in {"receipt", "output"})


async def test_output_identity_cannot_change_after_its_inspected_bytes_are_journaled(
    engine, monkeypatch, tmp_path
):
    rows, operation, journal = await prepared(engine, monkeypatch, tmp_path)
    await journal.start(rows.begun.dispatch_context)
    metadata = MediaInfo(kind="video", media_type="video/mp4", byte_size=4, duration_seconds=1)
    first = await journal.output(b"clip", metadata)
    second = await journal.output(b"clip", metadata)
    assert first.output_file_id == second.output_file_id == operation.output_file_id
    for data, changed in (
        (b"else", metadata),
        (b"clip", metadata.model_copy(update={"byte_size": 5})),
        (b"clip", metadata.model_copy(update={"kind": "image"})),
        (
            b"x" * (operation.reserved_bytes + 1),
            metadata.model_copy(update={"byte_size": operation.reserved_bytes + 1}),
        ),
    ):
        with pytest.raises(MediaOperationError, match="output"):
            await journal.output(data, changed)
    await journal.reject_output(reason="MEDIA_OUTPUT_REFUSED")
    row = await journal.read()
    assert row.phase == "failed" and row.held_bytes == 0 and row.held_usd == operation.reserved_usd
    await journal.output(b"clip", metadata)
    assert (await journal.read()).phase == "failed"
