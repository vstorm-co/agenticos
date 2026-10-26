"""A session ends where a person leaves it: an equal later round and its own exposures decide nothing."""

from datetime import UTC, datetime

import pytest

from app.db.models.authoring import BatchStatus
from app.db.models.improvement import ImprovementRun
from app.repositories import authoring_repo, improvement_repo
from app.schemas.improvement import ImprovementFinish
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_pipeline import _ready_proposal

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _equal_second_round(db, ctx, agent, ready):
    """Round 2 as judging finds it after Improve again: its own batch, measured as well as round 1."""
    org = ctx.organization_id
    run = await db.get(ImprovementRun, ready.id)
    [first] = await improvement_repo.list_iterations(db, organization_id=org, run_id=run.id)
    batch = await authoring_repo.create_batch(
        db,
        organization_id=org,
        agent_id=agent.id,
        request_id=None,
        source_started_at=datetime.now(UTC),
        expected_effect="round two",
        evidence_conversation_ids=[],
        improvement_run_id=run.id,
    )
    second = await improvement_repo.create_iteration(
        db, organization_id=org, run_id=run.id, number=2
    )
    await improvement_repo.update_iteration(
        db,
        iteration=second,
        values={
            "batch_id": batch.id,
            "eval_run_ids": list(first.eval_run_ids),
            "candidate_spec_hash": first.candidate_spec_hash,
            "included_hunk_ids": [],
        },
    )
    run.max_iterations, run.iteration, run.status, run.stage = 3, 2, "running", "judging"
    await db.flush()
    return run, first, second, batch


async def test_an_equal_second_round_leaves_the_best_round_waiting_and_acceptable(db):
    ctx, agent, ready = await _ready_proposal(db)
    run, first, _, second_batch = await _equal_second_round(db, ctx, agent, ready)
    service = ImprovementPipelineService(db)

    await service.advance(run.id, ctx.organization_id)
    judged = await service.read(ctx, agent.id, run.id)
    assert (judged.status, judged.best_iteration_id) == ("ready", first.id)
    batch = await authoring_repo.get_batch(db, first.batch_id, organization_id=ctx.organization_id)
    assert batch.status == "open" and second_batch.status != "open"

    await service.advance(run.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, run.id)).status == "ready"
    finished = await service.finish(
        ctx, agent.id, run.id, ImprovementFinish(confirmed=True, publish=True)
    )
    assert finished.session.status == "published"


async def test_a_batch_its_own_session_superseded_is_not_a_rejection(db):
    ctx, agent, ready = await _ready_proposal(db)
    run, first, second, second_batch = await _equal_second_round(db, ctx, agent, ready)
    first_batch = await authoring_repo.get_batch(
        db, first.batch_id, organization_id=ctx.organization_id
    )
    await authoring_repo.close_batch(db, batch=first_batch, status=BatchStatus.SUPERSEDED)
    second_batch.status = "open"
    run.status, run.stage, run.best_iteration_id = "ready", "judging", first.id
    await db.flush()

    await ImprovementPipelineService(db).advance(run.id, ctx.organization_id)
    assert (await ImprovementPipelineService(db).read(ctx, agent.id, run.id)).status == "ready"

    second_batch.improvement_run_id = None
    await db.flush()
    await ImprovementPipelineService(db).advance(run.id, ctx.organization_id)
    assert (await ImprovementPipelineService(db).read(ctx, agent.id, run.id)).status == "rejected"
