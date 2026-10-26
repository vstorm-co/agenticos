"""Concurrent starts distinguish the known active-session race from unrelated database errors."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConcurrentChangeError
from app.db.models.improvement import ImprovementRun
from app.schemas.improvement import ImprovementStart
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_evidence import _serial_worker as _serial_worker
from tests.integration.test_improvement_pipeline import _ready_proposal, _started

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


class ConstraintConflict(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


@pytest.mark.parametrize("failure", ["direct", "wrapped", "unrelated", "winner_deleted"])
async def test_a_start_collision_only_translates_the_known_active_session_constraint(
    db: AsyncSession, failure: str
) -> None:
    ctx, agent, dataset, session = await _started(db)
    service = ImprovementPipelineService(db)
    await service.cancel(ctx, agent.id, session.id)
    winner = ImprovementRun(
        id=uuid4(), organization_id=ctx.organization_id, agent_id=agent.id, status="queued"
    )
    cause = ConstraintConflict(
        "another_constraint" if failure == "unrelated" else "uq_improvement_runs_active"
    )
    original: Exception = cause
    if failure == "wrapped":
        original = RuntimeError("database driver wrapper")
        original.__cause__ = cause
    conflict = IntegrityError("INSERT improvement_runs", {}, original)
    error = IntegrityError if failure in {"unrelated", "winner_deleted"} else ConcurrentChangeError
    count = await db.scalar(select(func.count()).select_from(ImprovementRun))
    with (
        patch(
            "app.services.improvement_pipeline.improvement_repo.get_active",
            AsyncMock(side_effect=[None, None if failure == "winner_deleted" else winner]),
        ),
        patch(
            "app.services.improvement_pipeline.improvement_repo.create_run",
            AsyncMock(side_effect=conflict),
        ),
        pytest.raises(error) as refused,
    ):
        await service.start(
            ctx,
            agent.id,
            ImprovementStart(dataset_id=dataset.id, max_iterations=1, budget_usd=Decimal("5")),
        )
    if isinstance(refused.value, ConcurrentChangeError):
        assert refused.value.details == {"improvement_run_id": str(winner.id)}
    else:
        assert refused.value is conflict
    assert await db.scalar(select(func.count()).select_from(ImprovementRun)) == count


async def test_a_failed_eval_retry_keeps_its_checks_and_duplicate_clicks_start_no_second_check(
    db: AsyncSession,
) -> None:
    ctx, agent, session = await _ready_proposal(db)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    service = ImprovementPipelineService(db)
    with pytest.raises(BadRequestError, match="failed"):
        await service.retry(ctx, agent.id, session.id)
    row.status, row.stage = "failed", "evaluating"
    await db.flush()
    retried = await service.retry(ctx, agent.id, session.id)
    repeated = await service.retry(ctx, agent.id, session.id)
    assert retried.status == "running"
    assert len(retried.iterations[0].eval_run_ids) == len(session.iterations[0].eval_run_ids) + 1
    assert repeated.iterations[0].eval_run_ids == retried.iterations[0].eval_run_ids


async def test_retry_cannot_reserve_work_while_a_newer_session_is_active(db: AsyncSession) -> None:
    ctx, agent, dataset, session = await _started(db)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    row.status, row.stage = "failed", "proposing"
    await db.flush()
    service = ImprovementPipelineService(db)
    newer = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, max_iterations=1, budget_usd=Decimal("5")),
    )
    with pytest.raises(ConcurrentChangeError, match="running"):
        await service.retry(ctx, agent.id, session.id)
    assert (await service.read(ctx, agent.id, newer.id)).status == "queued"


async def _winner(db: AsyncSession, row: ImprovementRun) -> ImprovementRun:
    """Another session that took the agent after the loser looked and found none."""
    from app.repositories import improvement_repo

    return await improvement_repo.create_run(
        db,
        organization_id=row.organization_id,
        agent_id=row.agent_id,
        created_by_user_id=row.created_by_user_id,
        created_by_api_key_id=None,
        base_version_id=row.base_version_id,
        base_draft_hash=row.base_draft_hash,
        dataset_id=row.dataset_id,
        dataset_version=row.dataset_version,
        suite_id=None,
        suite_hash=None,
        scoring_hash=row.scoring_hash,
        window_days=row.window_days,
        estimate_usd=row.estimate_usd,
        budget_usd=row.budget_usd,
        max_iterations=row.max_iterations,
    )


@pytest.mark.parametrize("resume", ["retry", "continue"])
async def test_a_resume_that_loses_the_race_to_another_session_is_a_conflict(
    db: AsyncSession, resume: str
) -> None:
    from app.schemas.improvement import ContinuationConsent, ImprovementContinue

    ctx, agent, session = await _ready_proposal(db)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    service = ImprovementPipelineService(db)
    if resume == "retry":
        row.status, row.stage, row.stop_reason = "failed", "proposing", "proposal"
        await db.flush()

        async def act() -> object:
            return await service.retry(ctx, agent.id, session.id)
    else:
        row.max_iterations = 3
        await db.flush()
        quote = await service.estimate_continuation(
            ctx, agent.id, session.id, ImprovementContinue(budget_usd=Decimal("5"))
        )
        consent = ContinuationConsent(
            confirmed=True,
            budget_usd=quote.budget_usd,
            estimate_usd=quote.total_usd,
            candidate_hash=quote.candidate_hash,
        )

        async def act() -> object:
            return await service.continue_run(ctx, agent.id, session.id, consent)

    status = row.status
    winner = await _winner(db, row)
    from app.repositories import improvement_repo

    found = improvement_repo.get_active
    looked: list[bool] = []

    async def looked_too_early(*args: object, **kwargs: object) -> ImprovementRun | None:
        if not looked:
            looked.append(True)
            return None
        return await found(*args, **kwargs)

    with (
        patch(
            "app.services.improvement_pipeline.improvement_repo.get_active",
            side_effect=looked_too_early,
        ),
        pytest.raises(ConcurrentChangeError) as refused,
    ):
        await act()
    assert refused.value.details == {"improvement_run_id": str(winner.id)}
    assert isinstance(refused.value.__cause__, IntegrityError)
    await db.refresh(row)
    assert row.status == status
