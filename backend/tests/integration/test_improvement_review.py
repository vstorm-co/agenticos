"""Human review updates the wizard's verdict without another paid run or publication."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.db.models.case_score import CaseScore
from app.db.models.eval_run import EvalRun, EvalRunArm, EvalRunCase
from app.db.models.organization import OrganizationMember
from app.repositories import improvement_repo
from app.schemas.scoring import CaseVerdict
from app.services.eval_run import EvalRunService
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.scoring import ScoringService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_pipeline import _ready_proposal

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _scores(db, check_id):
    return list(
        (
            await db.execute(
                select(EvalRunArm.role, EvalRunCase.case_id, CaseScore)
                .join(EvalRunCase, EvalRunCase.arm_id == EvalRunArm.id)
                .join(CaseScore, CaseScore.id == EvalRunCase.case_score_id)
                .where(EvalRunCase.eval_run_id == check_id)
                .order_by(EvalRunCase.attempt)
            )
        ).all()
    )


async def test_review_and_undo_refresh_the_current_round_without_running_or_publishing(db):
    ctx, agent, ready = await _ready_proposal(db)
    check_id = ready.iterations[0].eval_run_ids[-1]
    rows = await _scores(db, check_id)
    case_id = rows[0][1]
    selected = [(role, score) for role, case, score in rows if case == case_id]
    original = dict(agent.draft_spec)
    version = agent.current_version_id
    count = await db.scalar(select(func.count()).select_from(EvalRun))
    service = ScoringService(db)
    for role, score in selected:
        await service.set_verdict(
            ctx,
            ready.dataset_id,
            score.id,
            CaseVerdict(passed=role == "baseline", note="Reviewed by a person"),
        )
    current = await ImprovementPipelineService(db).read(ctx, agent.id, ready.id)
    assert current.status == "ready"
    assert current.best_iteration_id == ready.best_iteration_id
    assert current.iterations[0].verdict == "regression"
    assert current.iterations[0].verdict_detail["broken"] == 1
    assert current.iterations[0].verdict_detail["fixed"] == 4
    assert current.iterations[0].eval_run_ids == ready.iterations[0].eval_run_ids
    assert current.spent_usd == ready.spent_usd
    assert agent.draft_spec == original and agent.current_version_id == version
    assert await db.scalar(select(func.count()).select_from(EvalRun)) == count
    child = await EvalRunService(db).get(ctx, check_id)
    assert child.review is not None and child.review.by_user_id == ctx.user_id
    assert child.review.by_name is not None
    for _, score in selected:
        await service.set_verdict(ctx, ready.dataset_id, score.id, CaseVerdict(passed=None))
    restored = await ImprovementPipelineService(db).read(ctx, agent.id, ready.id)
    assert restored.iterations[0].verdict == "better"
    assert restored.iterations[0].verdict_detail["broken"] == 0
    assert restored.iterations[0].verdict_detail["fixed"] == 5
    assert any(event.action == "improvement.review_recomputed" for event in restored.timeline)
    assert agent.draft_spec == original and agent.current_version_id == version


async def test_an_old_measurement_does_not_replace_the_selected_recheck(db):
    from tests.integration.test_improvement_selection import _consent, _finish_check, _hunks

    ctx, agent, ready = await _ready_proposal(db)
    old = ready.iterations[0].eval_run_ids[-1]
    service = ImprovementPipelineService(db)
    instruction = next(h for h in await _hunks(db, ctx, ready) if h.kind == "instructions")
    consent = await _consent(service, ctx, agent, ready, [instruction.id])
    await service.check_selection(ctx, agent.id, ready.id, 1, consent)
    current = await _finish_check(db, ctx, agent, ready)
    assert old in current.iterations[0].previous_eval_run_ids
    for role, _, score in await _scores(db, old):
        if role == "candidate":
            await ScoringService(db).set_verdict(
                ctx, ready.dataset_id, score.id, CaseVerdict(passed=False)
            )
    updated = await service.read(ctx, agent.id, ready.id)
    assert updated.iterations[0].eval_run_ids == current.iterations[0].eval_run_ids
    assert updated.iterations[0].verdict == "better"
    assert updated.iterations[0].verdict_detail["fixed"] == 5


async def test_a_departed_requester_cannot_leave_a_cached_green_verdict_after_review(db):
    ctx, agent, ready = await _ready_proposal(db)
    check_id = ready.iterations[0].eval_run_ids[-1]
    row = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == ctx.organization_id,
            OrganizationMember.user_id == ctx.user_id,
        )
    )
    # Simulate the requester no longer being resolvable without removing the
    # reviewer who is already authorized to decide this dataset score.
    from unittest.mock import AsyncMock

    with patch("app.services.improvement_pipeline.job_context", new=AsyncMock(return_value=None)):
        await ImprovementPipelineService(db).recompute_after_review(ctx, [check_id])
    assert row is not None
    current = await ImprovementPipelineService(db).read(ctx, agent.id, ready.id)
    assert (current.status, current.stop_reason) == ("stopped", "permission")
    assert current.iterations[0].verdict == "inconclusive"
    assert current.iterations[0].verdict_detail["fixed"] is None
    assert current.iterations[0].verdict_detail["broken"] is None
    assert current.iterations[0].verdict_detail["reason"] == "review_access_unavailable"


@pytest.mark.security
async def test_review_lookup_is_tenant_scoped_and_ignores_unrelated_checks(db):
    ctx, _, ready = await _ready_proposal(db)
    check_id = ready.iterations[0].eval_run_ids[-1]
    assert (
        await improvement_repo.runs_for_checks(db, organization_id=uuid4(), check_ids=[check_id])
        == []
    )
    assert (
        await improvement_repo.runs_for_checks(
            db, organization_id=ctx.organization_id, check_ids=[]
        )
        == []
    )
    assert (
        await improvement_repo.runs_for_checks(
            db, organization_id=ctx.organization_id, check_ids=[uuid4()]
        )
        == []
    )
