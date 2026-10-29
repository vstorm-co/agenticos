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
        "another_constraint" if failure == "unrelated" else "uq_improvement_runs_open"
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
            "app.services.improvement_pipeline.improvement_repo.get_open",
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


async def test_a_retry_of_an_agent_gone_under_its_lock_is_not_found(db: AsyncSession) -> None:
    from app.core.exceptions import NotFoundError

    ctx, agent, session = await _ready_proposal(db)
    with (
        patch("app.services.improvement_pipeline.agent_repo.lock", AsyncMock(return_value=None)),
        pytest.raises(NotFoundError),
    ):
        await ImprovementPipelineService(db).retry(ctx, agent.id, session.id)
