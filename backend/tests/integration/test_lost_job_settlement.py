"""A job withdrawn from the queue closes what it was queued for, through the worker's real path.

The settler tells a withdrawn job from a dead one by the `why` the queue hands
it, so this goes the whole way: the queue's own cancel, the rescuer's list of
ends still owed, the settler bound to the kind, and the end marked settled.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import anyio
import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.authoring import AuthoringStatus
from app.db.models.background_job import BackgroundJob
from app.db.models.eval_run import EvalRunStatus
from app.repositories import authoring_repo, eval_run_repo
from app.repositories import background_job as job_repo
from app.services.background_jobs import enqueue
from app.worker import handlers
from app.worker.jobs import RUN_AUTHORING, RUN_EVAL, RunAuthoring, RunEval
from tests.integration.test_authoring_repo import _agent, _org
from tests.integration.test_eval_runs_repo import _setup

pytestmark = pytest.mark.anyio


async def _withdraw_and_settle(db: AsyncSession, job_id: UUID) -> str:
    """Cancel the queued job as an administrator does, then settle what the rescuer finds owed."""
    assert await job_repo.cancel_queued(db, job_id)
    await db.commit()
    [end] = [end for end in await job_repo.unsettled_ends(db) if end.id == job_id]
    await handlers.settle_ended(end.kind, end.payload, end.why)
    await job_repo.mark_settled(db, job_id)
    await db.commit()
    return end.why


async def test_a_withdrawn_eval_job_cancels_its_run_and_skips_its_attempts(db) -> None:
    ctx, *_, run, _arm = await _setup(db, status=EvalRunStatus.QUEUED)
    job_id = await enqueue(
        db,
        RUN_EVAL,
        RunEval(eval_run_id=run.id, organization_id=ctx.organization_id),
        organization_id=ctx.organization_id,
    )
    assert job_id is not None
    await db.commit()

    why = await _withdraw_and_settle(db, job_id)

    await db.refresh(run)
    cases = await eval_run_repo.list_cases(db, run.id, organization_id=ctx.organization_id)
    job = await db.get(BackgroundJob, job_id)
    assert why == "cancelled"
    assert run.status == EvalRunStatus.CANCELLED.value
    assert {case.status for case in cases} == {"skipped"}
    assert job is not None and job.settled_at is not None


async def test_a_withdrawn_authoring_job_fails_its_request(db) -> None:
    org, user = await _org(db)
    agent = await _agent(db, org, user)
    request = await authoring_repo.create_request(
        db,
        organization_id=org.id,
        kind="improve",
        target="agent",
        agent_id=agent.id,
        skill_id=None,
        created_by_user_id=user.id,
        estimate_usd=Decimal("0.05"),
        window_days=30,
    )
    job_id = await enqueue(
        db,
        RUN_AUTHORING,
        RunAuthoring(request_id=request.id, organization_id=org.id),
        organization_id=org.id,
    )
    assert job_id is not None
    await db.commit()
    before = datetime.now(UTC)

    await _withdraw_and_settle(db, job_id)

    await db.refresh(request)
    assert request.status == AuthoringStatus.FAILED.value
    assert request.error == "The request was cancelled before it started. Try again."
    assert request.finished_at is not None and request.finished_at >= before


async def test_a_request_its_worker_still_holds_is_refused_at_once_not_waited_on(
    db, engine: AsyncEngine
) -> None:
    """The rescuer settles ends one after another, so one held row must not stall the rest."""
    org, user = await _org(db)
    agent = await _agent(db, org, user)
    request = await authoring_repo.create_request(
        db,
        organization_id=org.id,
        kind="improve",
        target="agent",
        agent_id=agent.id,
        skill_id=None,
        created_by_user_id=user.id,
        estimate_usd=Decimal("0.05"),
        window_days=30,
    )
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as worker, worker.begin():
        held = await authoring_repo.get_request(worker, request.id, organization_id=org.id)
        assert held is not None
        await authoring_repo.update_request(
            worker, request=held, values={"status": AuthoringStatus.RUNNING.value}
        )
        async with sessions() as settler:
            with anyio.fail_after(5), pytest.raises(DBAPIError) as refused:
                await authoring_repo.fail_unfinished(
                    settler,
                    request.id,
                    organization_id=org.id,
                    error="Stopped.",
                    now=datetime.now(UTC),
                )
    # lock_not_available: refused for the lock, not for anything else the database disliked.
    assert getattr(refused.value.orig, "sqlstate", None) == "55P03"
