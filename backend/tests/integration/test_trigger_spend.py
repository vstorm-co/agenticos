"""What a routine's runs have cost this month, against Postgres (#2575)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import agent_run_repo, agent_trigger_repo
from app.services.agent_runner import AgentRunnerService
from app.services.routine_health import RoutineHealthService
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
    run.routine_kind = "trigger"
    run.routine_origin_id = trigger.id
    await db.flush()
    return run


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


@pytest.mark.security
class TestAParkedFireResumedAfterItsMonthIsSpent:
    """A parked fire waits for the next month, as a fire skipped at admission does.

    A fire already running when the routine's limit is crossed finishes. One parked
    on an approval has not started its continuation, so resuming it after the month
    is spent is refused - before the approved call is replayed or the model is asked.
    """

    async def test_it_is_refused_once_the_routines_month_is_spent(self, db) -> None:
        user, org, agent, version, trigger = await _routine(db)
        now = datetime.now(UTC)
        await _run(db, org, agent, version, user, trigger, "4.00", now)
        parked = await _run(db, org, agent, version, user, trigger, "1.50", now)

        refusal = await AgentRunnerService(db)._routine_budget_spent(parked)

        assert refusal is not None
        assert (refusal.limit_usd, refusal.spent_usd) == (Decimal("5"), Decimal("5.50"))
        assert str(refusal).startswith("Routine monthly budget exhausted")

    async def test_it_resumes_while_the_routine_has_budget_left(self, db) -> None:
        user, org, agent, version, trigger = await _routine(db)
        now = datetime.now(UTC)
        await _run(db, org, agent, version, user, trigger, "2.00", now)
        parked = await _run(db, org, agent, version, user, trigger, "1.00", now)

        assert await AgentRunnerService(db)._routine_budget_spent(parked) is None

    async def test_a_fire_parked_last_month_answers_to_last_month(self, db) -> None:
        user, org, agent, version, trigger = await _routine(db)
        last_evening = month_start() - timedelta(hours=2)
        await _run(db, org, agent, version, user, trigger, "9.00", datetime.now(UTC))
        parked = await _run(db, org, agent, version, user, trigger, "1.00", last_evening)

        assert await AgentRunnerService(db)._routine_budget_spent(parked) is None

        await _run(db, org, agent, version, user, trigger, "4.50", last_evening)
        refusal = await AgentRunnerService(db)._routine_budget_spent(parked)

        assert refusal is not None and refusal.spent_usd == Decimal("5.50")

    async def test_a_refused_parked_fire_does_not_count_towards_the_automatic_pause(
        self, db
    ) -> None:
        """It waits for the next month; three of them must not switch the routine off."""
        user, org, agent, version, trigger = await _routine(db)
        now = datetime.now(UTC)
        await _run(db, org, agent, version, user, trigger, "4.00", now)
        for index in range(3):
            parked = await _run(db, org, agent, version, user, trigger, "1.00", now)
            assert await AgentRunnerService(db)._routine_budget_spent(parked) is not None
            parked.status = RunStatus.BUDGET_EXCEEDED.value
            parked.routine_activation_at = now + timedelta(minutes=index)
            await db.flush()
            await RoutineHealthService(db).run_result(parked)

        assert trigger.is_active and trigger.auto_stopped_at is None
        assert trigger.consecutive_failures == 0

    async def test_a_routine_without_a_limit_of_its_own_refuses_nothing(self, db) -> None:
        user, org, agent, version, trigger = await _routine(db)
        trigger.monthly_budget_usd = None
        await db.flush()
        parked = await _run(db, org, agent, version, user, trigger, "50", datetime.now(UTC))

        assert await AgentRunnerService(db)._routine_budget_spent(parked) is None
