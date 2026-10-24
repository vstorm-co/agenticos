"""Competing work and stale suggestions cannot start another paid measurement."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConcurrentChangeError, NotFoundError
from app.db.models.authoring import AuthoringRequest
from app.db.models.improvement import ImprovementRun
from app.repositories import improvement_repo
from app.schemas.improvement import AttributionConsent, ImprovementStart
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_continuation import _consent as continuation_consent
from tests.integration.test_improvement_pipeline import _ready_proposal
from tests.integration.test_improvement_selection import _consent, _hunks

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


@pytest.mark.parametrize("operation", ["continue", "selection"])
async def test_a_new_session_blocks_paid_work_in_an_older_waiting_session(
    db: AsyncSession, operation: str
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    assert row is not None
    row.max_iterations = 3
    await db.flush()
    service = ImprovementPipelineService(db)
    _, continuation = await continuation_consent(service, ctx, agent, ready)
    selected = await _consent(service, ctx, agent, ready, [(await _hunks(db, ctx, ready))[0].id])
    newer = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=ready.dataset_id, max_iterations=1, budget_usd=Decimal("5")),
    )
    before = await db.scalar(select(func.count()).select_from(AuthoringRequest))
    with pytest.raises(ConcurrentChangeError) as refused:
        if operation == "continue":
            await service.continue_run(ctx, agent.id, ready.id, continuation)
        else:
            await service.check_selection(ctx, agent.id, ready.id, 1, selected)
    assert refused.value.details is not None
    assert refused.value.details["improvement_run_id"] == str(newer.id)
    assert row.status == "ready"
    assert await db.scalar(select(func.count()).select_from(AuthoringRequest)) == before


@pytest.mark.parametrize("blocker", ["removed_agent", "another_selection", "active_check"])
async def test_selection_refuses_competing_or_missing_work_without_replacing_old_checks(
    db: AsyncSession, blocker: str
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    consent = await _consent(service, ctx, agent, ready, [(await _hunks(db, ctx, ready))[0].id])
    row = await db.get(ImprovementRun, ready.id)
    assert row is not None
    if blocker == "another_selection":
        row.status = "running"
        await db.flush()
    target = (
        "app.services.improvement_pipeline.agent_repo.lock"
        if blocker == "removed_agent"
        else "app.services.improvement_pipeline.improvement_repo.has_active_check"
    )
    error = NotFoundError if blocker == "removed_agent" else ConcurrentChangeError
    with (
        patch(target, AsyncMock(return_value=None if blocker == "removed_agent" else True)),
        pytest.raises(error),
    ):
        await service.check_selection(ctx, agent.id, ready.id, 1, consent)
    iteration = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=ready.id, number=1
    )
    assert iteration is not None and iteration.eval_run_ids == ready.iterations[0].eval_run_ids


@pytest.mark.parametrize(
    "blocker", ["unmeasured", "no_pending", "no_longer_applies", "active_check"]
)
async def test_individual_change_checks_refuse_unavailable_inputs(
    db: AsyncSession, blocker: str
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    iteration = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=ready.id, number=1
    )
    assert iteration is not None
    if blocker == "unmeasured":
        iteration.verdict = None
        await db.flush()
        with pytest.raises(NotFoundError, match="measured"):
            await service.estimate_attribution(ctx, agent.id, ready.id, 1)
    elif blocker == "active_check":
        with (
            patch(
                "app.services.improvement_pipeline.improvement_repo.has_active_check",
                AsyncMock(return_value=True),
            ),
            pytest.raises(ConcurrentChangeError, match="still running"),
        ):
            await service.start_attribution(
                ctx,
                agent.id,
                ready.id,
                1,
                AttributionConsent(confirmed=True, estimate_usd=Decimal("5")),
            )
    else:
        run, selected, inputs = await service._attribution_target(ctx, agent.id, ready.id, 1)
        hunks = await _hunks(db, ctx, ready)
        if blocker == "no_pending":
            for hunk in hunks:
                hunk.status = "dismissed"
        else:
            instruction = next(hunk for hunk in hunks if hunk.kind == "instructions")
            instruction.old_text = "This text is absent from the measured base"
        await db.flush()
        error = BadRequestError if blocker == "no_pending" else ConcurrentChangeError
        # Input pin validation remains intact; the race happens after the
        # attribution target was read, at the next repository read.
        with pytest.raises(error, match=r"pending|applies"):
            await service._attribution_changes(ctx, run, selected, inputs)
    assert iteration.attribution_eval_run_ids == {}


@pytest.mark.security
async def test_review_cannot_retain_a_green_result_after_the_requester_is_revoked(
    db: AsyncSession,
) -> None:
    from app.core.exceptions import AuthenticationError

    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    check_id = ready.iterations[0].eval_run_ids[-1]
    before = list(ready.iterations[0].eval_run_ids)
    with patch(
        "app.services.improvement_pipeline.job_context",
        AsyncMock(side_effect=AuthenticationError(message="The key was revoked")),
    ):
        await service.recompute_after_review(ctx, [check_id])
    refreshed = await service.read(ctx, agent.id, ready.id)
    assert refreshed.iterations[0].verdict == "inconclusive"
    assert refreshed.iterations[0].verdict_detail is not None
    assert refreshed.iterations[0].verdict_detail["fixed"] is None
    assert refreshed.iterations[0].eval_run_ids == before
