"""A lost worker or revoked boundary stops the parent without another paid attempt."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    PaymentRequiredError,
)
from app.db.models.authoring import AuthoringRequest
from app.db.models.eval_run import EvalRun
from app.db.models.improvement import ImprovementRun
from app.db.models.organization import Organization
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_evidence import _serial_worker as _serial_worker
from tests.integration.test_improvement_pipeline import _ready_proposal, _started, _until_child

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


@pytest.mark.security
@pytest.mark.parametrize(
    "boundary",
    [
        "authentication",
        "authorization",
        "missing_grant",
        "bad_request",
        "ai_disabled",
        "budget",
        "provider",
    ],
)
async def test_boundary_failure_is_recorded_before_a_paid_child_can_start(
    db: AsyncSession, boundary: str
) -> None:
    ctx, agent, _, session = await _started(db)
    service = ImprovementPipelineService(db)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    row.stage = "proposing"
    await db.flush()
    if boundary == "ai_disabled":
        org = await db.get(Organization, ctx.organization_id)
        assert org is not None
        org.ai_assistance_enabled = False
        await db.flush()
        await service.advance(session.id, ctx.organization_id)
    elif boundary in {"budget", "provider"}:
        error = (
            PaymentRequiredError(message="No remaining funds")
            if boundary == "budget"
            else BadRequestError(message="Provider refused this request")
        )
        with patch.object(service, "_step", AsyncMock(side_effect=error)):
            await service.advance(session.id, ctx.organization_id)
    else:
        error = {
            "authentication": AuthenticationError(message="Revoked account"),
            "authorization": AuthorizationError(message="Edit grant removed"),
            "missing_grant": NotFoundError(message="Dataset no longer visible"),
            "bad_request": BadRequestError(message="Archived resource"),
        }[boundary]
        target = (
            "app.services.improvement_pipeline.job_context"
            if boundary == "authentication"
            else "app.services.improvement_pipeline.ImprovementPipelineService._inputs"
        )
        with patch(target, AsyncMock(side_effect=error)):
            await service.advance(session.id, ctx.organization_id)
    expected = ("stopped", "permission")
    if boundary == "bad_request":
        expected = ("stale", "stale")
    if boundary == "budget":
        expected = ("stopped", "budget")
    if boundary == "provider":
        expected = ("failed", "proposal")
    read = await service.read(ctx, agent.id, session.id)
    assert (read.status, read.stop_reason) == expected
    assert read.iterations[0].authoring_request_id is None
    if boundary == "provider":
        assert read.error == "Provider refused this request"


@pytest.mark.parametrize("running", [False, True])
async def test_only_a_running_proposal_without_progress_can_stall(
    db: AsyncSession,
    running: bool,
) -> None:
    ctx, agent, _, session = await _started(db)
    await _until_child(db, ctx, session.id)
    service = ImprovementPipelineService(db)
    read = await service.read(ctx, agent.id, session.id)
    request_id = read.iterations[0].authoring_request_id
    request = await db.get(AuthoringRequest, request_id)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None and request is not None
    old = datetime.now(UTC) - timedelta(hours=2)
    row.created_at = row.stage_started_at = old
    request.status = "running" if running else "queued"
    request.started_at = request.heartbeat_at = old if running else None
    await db.flush()
    await service.advance(session.id, ctx.organization_id)
    await db.refresh(request)
    stopped = await service.read(ctx, agent.id, session.id)
    assert (stopped.status, stopped.stop_reason) == (
        ("failed", "stalled") if running else ("running", None)
    )
    assert request.status == ("failed" if running else "queued")
    await service.advance(session.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, session.id)).iterations[
        0
    ].authoring_request_id == request_id


@pytest.mark.parametrize("running", [False, True])
async def test_only_a_running_measurement_without_progress_can_stall(
    db: AsyncSession,
    running: bool,
) -> None:
    ctx, agent, session = await _ready_proposal(db)
    row = await db.get(ImprovementRun, session.id)
    child = await db.get(EvalRun, session.iterations[0].eval_run_ids[-1])
    assert row is not None and child is not None
    old = datetime.now(UTC) - timedelta(hours=13)
    row.status, row.stage = "running", "evaluating"
    row.created_at = row.stage_started_at = old
    child.status = "running" if running else "queued"
    child.started_at = child.heartbeat_at = old if running else None
    child.ended_at = None
    await db.flush()
    service = ImprovementPipelineService(db)
    await service.advance(session.id, ctx.organization_id)
    await db.refresh(child)
    stopped = await service.read(ctx, agent.id, session.id)
    assert (stopped.status, stopped.stop_reason) == (
        ("failed", "stalled") if running else ("running", None)
    )
    assert child.status == ("cancelled" if running else "queued")


async def test_a_deleted_proposal_request_fails_the_parent_without_a_new_paid_request(
    db: AsyncSession,
) -> None:
    ctx, agent, _, session = await _started(db)
    await _until_child(db, ctx, session.id)
    service = ImprovementPipelineService(db)
    before = await service.read(ctx, agent.id, session.id)
    with patch(
        "app.services.improvement_pipeline.authoring_repo.get_request",
        AsyncMock(return_value=None),
    ):
        await service.advance(session.id, ctx.organization_id)
    stopped = await service.read(ctx, agent.id, session.id)
    assert (stopped.status, stopped.stop_reason) == ("failed", "proposal")
    assert stopped.iterations[0].authoring_request_id == before.iterations[0].authoring_request_id


async def test_a_waiting_session_without_a_selected_round_makes_no_authoring_decision(
    db: AsyncSession,
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    assert row is not None
    row.best_iteration_id = None
    await db.flush()
    before = dict(agent.draft_spec)
    service = ImprovementPipelineService(db)
    await service.advance(ready.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, ready.id)).status == "ready"
    assert agent.draft_spec == before
