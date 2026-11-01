"""What a routine's runs have cost this month, against Postgres (#2575)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import RunSurface
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import agent_run_repo, agent_trigger_repo
from app.services.spend import month_start

pytestmark = pytest.mark.anyio


async def _routine(db: AsyncSession):
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    agent = Agent(
        organization_id=org.id,
        name="Finance",
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(agent_id=agent.id, organization_id=org.id, version=1, spec={})
    db.add(version)
    await db.flush()
    trigger = await agent_trigger_repo.create(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        prompt="Watch",
        name=None,
        trigger_type="schedule",
        schedule_kind="interval",
        interval_seconds=600,
        cron_expression=None,
        event_source=None,
        event_config={},
        event_secret_encrypted=None,
        secret_key_version=None,
        environment_id=None,
        next_fire_at=datetime.now(UTC),
        monthly_budget_usd=Decimal("5"),
    )
    return user, org, agent, version, trigger


async def _run(db, org, agent, version, user, trigger, cost: str, started_at: datetime):
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=user.id,
        conversation_id=None,
        surface=RunSurface.SCHEDULE.value,
        model_label="m",
        started_at=started_at,
    )
    run.cost_usd = Decimal(cost)
    run.trigger_id = trigger.id
    await db.flush()


async def test_a_routines_month_is_the_cost_of_the_runs_it_started_this_month(
    db: AsyncSession,
) -> None:
    user, org, agent, version, trigger = await _routine(db)
    other = await agent_trigger_repo.create(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        prompt="Other",
        name=None,
        trigger_type="schedule",
        schedule_kind="interval",
        interval_seconds=600,
        cron_expression=None,
        event_source=None,
        event_config={},
        event_secret_encrypted=None,
        secret_key_version=None,
        environment_id=None,
        next_fire_at=datetime.now(UTC),
    )
    now = datetime.now(UTC)
    await _run(db, org, agent, version, user, trigger, "1.25", now)
    await _run(db, org, agent, version, user, trigger, "2.00", now)
    await _run(db, org, agent, version, user, trigger, "9.00", month_start() - timedelta(days=1))
    await _run(db, org, agent, version, user, other, "0.50", now)

    spent = await agent_run_repo.spend_by_trigger_since(
        db, trigger_ids=[trigger.id, other.id, uuid.uuid4()], since=month_start()
    )

    assert spent == {trigger.id: Decimal("3.25"), other.id: Decimal("0.50")}
    assert (
        await agent_run_repo.spend_by_trigger_since(db, trigger_ids=[], since=month_start()) == {}
    )
