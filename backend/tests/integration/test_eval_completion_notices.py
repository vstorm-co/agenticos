"""Completion is addressed once to the requester, without question text or child spam."""

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.case_generation import CaseGeneration
from app.db.models.eval_run import EvalRun
from app.db.models.notification import Notification
from app.db.models.organization import OrganizationMember
from app.repositories import case_generation_repo
from app.schemas.eval_run import EvalRunRequest
from app.services.agent_runner import AgentRunnerService
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker
from app.services.notifications import NotificationService
from app.services.run_reaper import RunReaperService
from tests.integration.test_eval_suites import Model, _agent, _dataset, _owner, _sessions
from tests.integration.test_eval_suites import _environment as _environment

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


@pytest.fixture(autouse=True)
def _events():
    def dropped(_db, coro, *, name):
        coro.close()

    with patch("app.services.notifications.spawn_after_commit", side_effect=dropped) as queued:
        yield queued


async def test_manual_eval_notifies_once_and_announces_a_terminal_change(db, _events):
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    started = await EvalRunService(db).start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(db)

    async def execute(runner, *args, **kwargs):
        return await model.execute(runner, *args, **kwargs)

    with patch.object(AgentRunnerService, "execute", new=execute):
        worker = EvalRunWorker(started.id, ctx.organization_id, sessions=_sessions(db), heartbeat=0)
        await worker.run()
        await worker.run()
    notices = list(
        await db.scalars(select(Notification).where(Notification.event_type == "eval_run_finished"))
    )
    assert len(notices) == 1
    notice = notices[0]
    assert notice.recipient_user_id == ctx.user_id
    assert notice.organization_id == ctx.organization_id
    assert notice.context_url.startswith(f"/agents/{agent.id}/evals/{started.id}?")
    assert "30 days" not in str(notice.render_context)
    assert _events.call_count == 1
    run = await db.get(EvalRun, started.id)
    run.purpose = "gate"
    await NotificationService(db).eval_run_finished(run)
    assert len(list(await db.scalars(select(Notification)))) == 1


@pytest.mark.parametrize("why,status", [("cancelled", "cancelled"), ("worker killed", "failed")])
async def test_a_lost_job_notifies_without_waiting_for_a_worker(db, why, status):
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    started = await EvalRunService(db).start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    service = RunReaperService(db)
    await service.settle_lost_eval(started.id, organization_id=ctx.organization_id, why=why)
    await service.settle_lost_eval(started.id, organization_id=ctx.organization_id, why=why)
    notices = list(await db.scalars(select(Notification)))
    assert len(notices) == 1
    assert notices[0].render_context["status"] == status


async def test_generation_terminal_notice_is_scoped_deduplicated_and_silent_after_leaving(db):
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    generation = CaseGeneration(
        organization_id=ctx.organization_id,
        dataset_id=dataset.id,
        agent_id=agent.id,
        requested_by_user_id=ctx.user_id,
        sources=["agent"],
        requested_count=5,
        status="running",
    )
    db.add(generation)
    await db.flush()
    service = NotificationService(db)
    await service.case_generation_finished(generation)
    assert list(await db.scalars(select(Notification))) == []
    await case_generation_repo.finish_generation(
        db, generation, status="ready", proposed_count=5, finished_at=datetime.now(UTC)
    )
    await service.case_generation_finished(generation)
    await service.case_generation_finished(generation)
    notices = list(await db.scalars(select(Notification)))
    assert len(notices) == 1
    assert notices[0].recipient_user_id == ctx.user_id
    assert notices[0].context_url.startswith(f"/datasets/{dataset.id}?tab=generated&org=")
    assert notices[0].event_type == "case_generation_finished"
    membership = await db.scalar(
        select(OrganizationMember).where(OrganizationMember.user_id == ctx.user_id)
    )
    await db.delete(membership)
    await db.flush()
    generation = CaseGeneration(
        id=uuid4(),
        organization_id=ctx.organization_id,
        dataset_id=dataset.id,
        requested_by_user_id=ctx.user_id,
        status="ready",
    )
    await service.case_generation_finished(generation)
    assert len(list(await db.scalars(select(Notification)))) == 1


async def test_an_eval_still_going_announces_nothing(db, _events):
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    started = await EvalRunService(db).start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    run = await db.get(EvalRun, started.id)
    service = NotificationService(db)

    for status in ("queued", "running"):
        run.status = status
        await service.eval_run_finished(run)

    assert list(await db.scalars(select(Notification))) == []
    assert _events.call_count == 0


async def test_an_improvement_nobody_requested_notifies_nobody(db, _events):
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)

    await NotificationService(db).improvement_finished(
        agent=agent, run_id=uuid4(), user_id=None, status="ready", reason=None
    )

    assert list(await db.scalars(select(Notification))) == []
    assert _events.call_count == 0
