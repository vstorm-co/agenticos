"""Which rows the stale-run reap actually touches, against Postgres (#1078).

The write is one conditional UPDATE, so what it must not touch is as much the
contract as what it must: a run still inside its ceiling, a parked run with a
human resolver, and a run that already recorded its own outcome. A mock cannot
say which rows a WHERE returned; only the database can.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.services.run_reaper import RunReaperService

pytestmark = pytest.mark.anyio


async def _org(db: AsyncSession) -> Organization:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    )
    await db.flush()
    return org


async def _agent(db: AsyncSession, org: Organization) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(
    db: AsyncSession,
    org: Organization,
    agent: Agent,
    *,
    status: str,
    age: timedelta,
    transitioned: timedelta | None = None,
    beat: timedelta | None = None,
    modality: str = "text",
) -> AgentRun:
    """A run row `age` old; `transitioned` backdates its last UPDATE stamp, `beat` its heartbeat.

    `updated_at` and `heartbeat_at` stay null when not given, which is what a
    row that was opened and never touched again - the crash orphan - looks like.
    """
    now = datetime.now(UTC)
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        status=status,
        modality=modality,
        started_at=now - age,
        updated_at=None if transitioned is None else now - transitioned,
        heartbeat_at=None if beat is None else now - beat,
    )
    db.add(run)
    await db.flush()
    return run


async def test_only_the_crash_orphan_is_reaped(engine: AsyncEngine, db: AsyncSession):
    """The never-touched orphan and the run that stopped beating fall; the long
    run still beating, the fresh one, the parked run, the settled one, the
    freshly resumed one and the voice call stand - and the verdict is read from
    a fresh session, because a reap the sweep's own transaction never committed
    reaped nothing."""
    org = await _org(db)
    agent = await _agent(db, org)
    orphan = await _run(db, org, agent, status=RunStatus.RUNNING.value, age=timedelta(hours=7))
    # Its process died mid-turn, minutes ago: it beat, then stopped.
    silent = await _run(
        db,
        org,
        agent,
        status=RunStatus.RUNNING.value,
        age=timedelta(minutes=20),
        beat=timedelta(minutes=5),
    )
    # A model that takes half an hour is still a live run, as long as it beats.
    beating = await _run(
        db,
        org,
        agent,
        status=RunStatus.RUNNING.value,
        age=timedelta(minutes=30),
        beat=timedelta(seconds=10),
    )
    fresh_run = await _run(
        db, org, agent, status=RunStatus.RUNNING.value, age=timedelta(seconds=30)
    )
    # The voice reaper's, which hangs up the call and closes the run with it.
    call = await _run(
        db, org, agent, status=RunStatus.RUNNING.value, age=timedelta(hours=7), modality="voice"
    )
    parked = await _run(
        db, org, agent, status=RunStatus.AWAITING_APPROVAL.value, age=timedelta(hours=7)
    )
    settled = await _run(db, org, agent, status=RunStatus.COMPLETED.value, age=timedelta(hours=7))
    # A resume keeps the run's original start and re-marks it `running`, so its
    # age is its last transition: reaped on `started_at` it would fall the
    # moment its replay began, and a scheduled trigger could fire on top of the
    # approved call still executing.
    resumed = await _run(
        db,
        org,
        agent,
        status=RunStatus.RUNNING.value,
        age=timedelta(hours=7),
        transitioned=timedelta(seconds=30),
    )
    await db.commit()

    assert len(await RunReaperService(db).reap_stale()) == 2
    await db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as fresh:
        rows = {
            row.id: row
            for row in (
                (await fresh.execute(select(AgentRun).where(AgentRun.agent_id == agent.id)))
                .scalars()
                .all()
            )
        }
    assert rows[orphan.id].status == RunStatus.FAILED.value
    assert rows[orphan.id].ended_at is not None
    assert "died before recording an outcome" in (rows[orphan.id].error or "")
    assert rows[silent.id].status == RunStatus.FAILED.value
    assert rows[beating.id].status == RunStatus.RUNNING.value
    assert rows[fresh_run.id].status == RunStatus.RUNNING.value
    assert rows[call.id].status == RunStatus.RUNNING.value
    assert rows[parked.id].status == RunStatus.AWAITING_APPROVAL.value
    assert rows[settled.id].status == RunStatus.COMPLETED.value
    assert rows[resumed.id].status == RunStatus.RUNNING.value


async def test_a_beat_stamps_a_running_run_and_leaves_its_transition_alone(db: AsyncSession):
    """`updated_at` is the run's last transition, which the sweep reads too: a
    beat that moved it would make a resume's stamp indistinguishable from life.
    A run that already ended is not stamped at all."""
    org = await _org(db)
    agent = await _agent(db, org)
    running = await _run(
        db,
        org,
        agent,
        status=RunStatus.RUNNING.value,
        age=timedelta(minutes=10),
        transitioned=timedelta(minutes=10),
    )
    settled = await _run(
        db, org, agent, status=RunStatus.COMPLETED.value, age=timedelta(minutes=10)
    )
    transition = running.updated_at
    await db.commit()

    at = datetime.now(UTC)
    await agent_run_repo.beat_run(db, run_id=running.id, at=at)
    await agent_run_repo.beat_run(db, run_id=settled.id, at=at)
    await db.commit()
    await db.refresh(running)
    await db.refresh(settled)

    assert running.heartbeat_at == at
    assert running.updated_at == transition
    assert settled.heartbeat_at is None
