"""Knowledge-step recovery uses current budgets, tenant ownership and progress."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.improvement import ImprovementRun
from app.repositories import improvement_repo
from app.schemas.improvement import ImprovementContinue, ImprovementStart
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_eval_suites import _owner
from tests.integration.test_improvement_evidence import _serial_worker as _serial_worker
from tests.integration.test_improvement_knowledge_steps import (
    _classify,
    _job,
    _providers,
    _start,
    _world,
)

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


@pytest.mark.security
async def test_an_unfunded_classification_is_not_queued(db: AsyncSession) -> None:
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx):
        service = ImprovementPipelineService(db)
        read = await service.start(
            ctx,
            agent.id,
            ImprovementStart(dataset_id=dataset.id, max_iterations=1, budget_usd=Decimal("5")),
        )
        await service.advance(read.id, ctx.organization_id)
        await service.advance(read.id, ctx.organization_id)
        row = await db.get(ImprovementRun, read.id)
        assert row is not None and row.stage == "classifying"
        row.budget_usd = Decimal("0.000001")
        await db.flush()
        await service.advance(read.id, ctx.organization_id)
        stopped = await service.read(ctx, agent.id, read.id)
        assert (stopped.status, stopped.stop_reason) == ("stopped", "budget")
        iteration = await improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=read.id, number=1
        )
        assert iteration is not None and iteration.classify_job_id is None


async def test_a_running_classifier_without_progress_stops_the_parent(db: AsyncSession) -> None:
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        row = await db.get(ImprovementRun, read.id)
        assert row is not None
        job, _ = await _job(db, row)
        old = datetime.now(UTC) - timedelta(hours=1)
        row.created_at = row.stage_started_at = job.started_at = old
        job.status = "running"
        await db.flush()
        service = ImprovementPipelineService(db)
        await service.advance(read.id, ctx.organization_id)
        stopped = await service.read(ctx, agent.id, read.id)
        assert (stopped.status, stopped.stop_reason) == ("failed", "stalled")


async def test_a_dead_drafter_keeps_classification_and_reports_its_failure(
    db: AsyncSession,
) -> None:
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        row, _ = await _classify(db, ctx, agent, read)
        job, _ = await _job(db, row, draft=True)
        job.status = "dead"
        await db.flush()
        service = ImprovementPipelineService(db)
        await service.advance(read.id, ctx.organization_id)
        failed = await service.read(ctx, agent.id, read.id)
        assert any(event.action == "improvement.drafting_failed" for event in failed.timeline)
        assert failed.stage == "proposing"


@pytest.mark.security
async def test_a_cross_tenant_job_reference_cannot_be_reused_for_continuation(
    db: AsyncSession,
) -> None:
    ctx, agent, _, dataset, _ = await _world(db)
    other = await _owner(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        row = await db.get(ImprovementRun, read.id)
        assert row is not None
        job, _ = await _job(db, row)
        job.organization_id = other.organization_id
        row.status, row.stop_reason = "stopped", "budget"
        await db.flush()
        with pytest.raises(NotFoundError, match="Knowledge step"):
            await ImprovementPipelineService(db).estimate_continuation(
                ctx, agent.id, read.id, ImprovementContinue(budget_usd=Decimal("5"))
            )
