"""Which rows the stale-run reap actually touches, against Postgres (#1078).

The write is one conditional UPDATE, so what it must not touch is as much the
contract as what it must: a run still inside its ceiling, a parked run with a
human resolver, and a run that already recorded its own outcome. A mock cannot
say which rows a WHERE returned; only the database can.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
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
    db: AsyncSession, org: Organization, agent: Agent, *, status: str, age: timedelta
) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        status=status,
        started_at=datetime.now(UTC) - age,
    )
    db.add(run)
    await db.flush()
    return run


async def test_only_the_crash_orphan_is_reaped(engine: AsyncEngine, db: AsyncSession):
    """One old `running` row falls; its fresh sibling, the parked run and the
    settled one stand - and the verdict is read from a fresh session, because a
    reap the sweep's own transaction never committed reaped nothing."""
    org = await _org(db)
    agent = await _agent(db, org)
    orphan = await _run(db, org, agent, status=RunStatus.RUNNING.value, age=timedelta(hours=7))
    alive = await _run(db, org, agent, status=RunStatus.RUNNING.value, age=timedelta(minutes=5))
    parked = await _run(
        db, org, agent, status=RunStatus.AWAITING_APPROVAL.value, age=timedelta(hours=7)
    )
    settled = await _run(db, org, agent, status=RunStatus.COMPLETED.value, age=timedelta(hours=7))
    await db.commit()

    assert await RunReaperService(db).reap_stale() == 1
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
    assert rows[alive.id].status == RunStatus.RUNNING.value
    assert rows[parked.id].status == RunStatus.AWAITING_APPROVAL.value
    assert rows[settled.id].status == RunStatus.COMPLETED.value
