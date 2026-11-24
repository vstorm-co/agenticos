"""Persistent streaks are ordered by activation, bounded and independent of acknowledgement."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.routine_health import RoutineHealthObservation
from app.db.models.user import User
from app.db.models.watch import Watch, WatchAttemptStatus
from app.repositories import routine_health as repo
from app.services.routine_health import RoutineHealthService

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 3, tzinfo=UTC)


@dataclass
class World:
    parent: AgentTrigger | Watch
    user_id: UUID
    agent_id: UUID
    organization_id: UUID


async def world(db: AsyncSession, *, watch: bool = False) -> World:
    user = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=uuid4().hex, created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    agent = Agent(organization_id=org.id, name="Monitor", slug=uuid4().hex)
    db.add_all([agent, OrganizationMember(organization_id=org.id, user_id=user.id, role="owner")])
    await db.flush()
    parent: AgentTrigger | Watch
    if watch:
        connection = McpConnection(user_id=user.id, name="Source", url="https://source.example.com")
        db.add(connection)
        await db.flush()
        parent = Watch(
            organization_id=org.id,
            user_id=user.id,
            connection_id=connection.id,
            title="Source",
            instructions="Check",
            interval_minutes=60,
            next_run_at=NOW,
        )
    else:
        parent = AgentTrigger(
            organization_id=org.id,
            agent_id=agent.id,
            created_by_user_id=user.id,
            prompt="Check",
            interval_seconds=300,
            next_fire_at=NOW,
        )
    db.add(parent)
    await db.flush()
    return World(parent, user.id, agent.id, org.id)


def run(w: World, index: int, *, status: RunStatus = RunStatus.FAILED) -> AgentRun:
    at = NOW + timedelta(minutes=index)
    return AgentRun(
        id=uuid4(),
        organization_id=w.organization_id,
        agent_id=w.agent_id,
        user_id=w.user_id,
        status=status.value,
        started_at=at,
        ended_at=at,
        routine_activation_at=at,
        routine_kind="watch" if isinstance(w.parent, Watch) else "trigger",
        routine_origin_id=w.parent.id,
    )


async def count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(RoutineHealthObservation)) or 0


@pytest.mark.parametrize("watch", [False, True])
async def test_three_distinct_failures_stop_even_when_callbacks_arrive_out_of_order(
    db: AsyncSession, watch: bool
) -> None:
    w = await world(db, watch=watch)
    service = RoutineHealthService(db)
    for index in (3, 1, 2):
        await service.run_result(run(w, index))
    assert not w.parent.is_active and w.parent.consecutive_failures == 3
    assert w.parent.auto_stopped_at is not None and await count(db) == 3
    stopped = w.parent.auto_stopped_at
    await service.run_result(run(w, 4))
    assert w.parent.auto_stopped_at == stopped and await count(db) == 3


@pytest.mark.parametrize("watch", [False, True])
async def test_replayed_activation_counts_once_and_a_late_success_preserves_activation_order(
    db: AsyncSession, watch: bool
) -> None:
    w = await world(db, watch=watch)
    service = RoutineHealthService(db)
    for _ in range(3):
        await service.run_result(run(w, 3))
    await service.run_result(run(w, 1))
    assert w.parent.consecutive_failures == 2 and w.parent.is_active
    if isinstance(w.parent, Watch):
        await service.watch_result(
            w.parent, at=NOW + timedelta(minutes=2), status=WatchAttemptStatus.COMPLETED
        )
    else:
        await service.run_result(run(w, 2, status=RunStatus.COMPLETED))
    assert w.parent.consecutive_failures == 1 and w.parent.is_active
    assert await count(db) == 3


async def test_disabling_the_policy_and_resuming_start_a_fresh_window(db: AsyncSession) -> None:
    w = await world(db)
    service = RoutineHealthService(db)
    w.parent.max_failures = None
    await db.flush()
    await service.run_result(run(w, 1))
    assert w.parent.is_active and await count(db) == 0
    w.parent.max_failures = 1
    await db.flush()
    await service.run_result(run(w, 1))
    assert not w.parent.is_active
    w.parent.is_active = True
    w.parent.auto_stopped_at = None
    w.parent.health_reset_at = NOW + timedelta(minutes=2)
    w.parent.consecutive_failures = 0
    await db.flush()
    await service.run_result(run(w, 1))
    assert w.parent.is_active and w.parent.consecutive_failures == 0
    await service.run_result(run(w, 3))
    assert not w.parent.is_active and w.parent.consecutive_failures == 1


async def test_waiting_for_a_person_is_not_failure_or_a_successful_read(db: AsyncSession) -> None:
    w = await world(db, watch=True)
    assert isinstance(w.parent, Watch)
    service = RoutineHealthService(db)
    parked = run(w, 1, status=RunStatus.AWAITING_APPROVAL)
    await service.run_result(parked)
    await service.watch_result(
        w.parent, at=NOW, status=WatchAttemptStatus.NOT_COMPLETED, run=parked
    )
    await service.run_result(run(w, 2, status=RunStatus.COMPLETED))
    await service.watch_result(w.parent, at=NOW, status=WatchAttemptStatus.DELIVERY_UNAVAILABLE)
    await service.watch_result(w.parent, at=NOW, status=WatchAttemptStatus.BUDGET_PAUSED)
    assert await count(db) == 0 and w.parent.is_active


async def test_source_failures_count_and_a_verified_read_resets_the_streak(
    db: AsyncSession,
) -> None:
    w = await world(db, watch=True)
    assert isinstance(w.parent, Watch)
    service = RoutineHealthService(db)
    await service.watch_result(w.parent, at=NOW, status=WatchAttemptStatus.SOURCE_UNAVAILABLE)
    assert w.parent.consecutive_failures == 1
    await service.watch_result(
        w.parent, at=NOW + timedelta(minutes=1), status=WatchAttemptStatus.COMPLETED
    )
    assert w.parent.consecutive_failures == 0
    await service.watch_result(
        w.parent, at=NOW + timedelta(minutes=2), status=WatchAttemptStatus.SOURCE_UNAVAILABLE
    )
    budget = run(w, 3, status=RunStatus.BUDGET_EXCEEDED)
    await service.watch_result(
        w.parent, at=NOW + timedelta(minutes=3), status=WatchAttemptStatus.BUDGET_PAUSED, run=budget
    )
    assert w.parent.consecutive_failures == 1


@pytest.mark.security
@pytest.mark.parametrize("watch", [False, True])
async def test_budget_stops_wait_for_the_next_activation_and_do_not_pause(
    db: AsyncSession, watch: bool
) -> None:
    """A refused fire waits for the next one; it says nothing about the routine's health."""
    w = await world(db, watch=watch)
    service = RoutineHealthService(db)
    await service.run_result(run(w, 1))
    for index in (2, 3, 4):
        stopped = run(w, index, status=RunStatus.BUDGET_EXCEEDED)
        await service.run_result(stopped)
        if isinstance(w.parent, Watch):
            await service.watch_result(
                w.parent,
                at=stopped.routine_activation_at,
                status=WatchAttemptStatus.BUDGET_PAUSED,
                run=stopped,
            )
    assert w.parent.is_active and w.parent.auto_stopped_at is None
    assert w.parent.consecutive_failures == 1 and await count(db) == 1
    await service.run_result(run(w, 5))
    await service.run_result(run(w, 6))
    assert not w.parent.is_active and w.parent.consecutive_failures == 3


async def test_an_explicit_null_policy_is_stored_as_disabled_on_creation(db: AsyncSession) -> None:
    w = await world(db)
    second = AgentTrigger(
        organization_id=w.organization_id,
        agent_id=w.agent_id,
        created_by_user_id=w.user_id,
        prompt="Check",
        interval_seconds=300,
        next_fire_at=NOW,
        max_failures=None,
    )
    db.add(second)
    await db.flush()
    await db.refresh(second)
    assert second.max_failures is None


async def test_terminal_callbacks_cannot_touch_another_owner_or_organization(
    db: AsyncSession,
) -> None:
    w = await world(db)
    foreign = await world(db)
    service = RoutineHealthService(db)
    for organization_id, user_id in (
        (foreign.organization_id, w.user_id),
        (w.organization_id, foreign.user_id),
    ):
        result = run(w, 1)
        result.organization_id, result.user_id = organization_id, user_id
        await service.run_result(result)
    assert await count(db) == 0


async def test_only_fifty_observations_remain_and_deleting_the_parent_erases_them(
    db: AsyncSession,
) -> None:
    w = await world(db)
    for index in range(55):
        failures = await repo.observe(
            db,
            kind="trigger",
            routine_id=w.parent.id,
            organization_id=w.organization_id,
            user_id=w.user_id,
            activation_at=NOW + timedelta(minutes=index),
            healthy=index == 0,
            reset_at=None,
        )
    assert failures == 20 and await count(db) == 50
    await db.delete(w.parent)
    await db.flush()
    assert await count(db) == 0


async def test_two_workers_count_the_same_activation_once(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    w = await world(db)
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def report() -> None:
        async with factory() as session:
            await RoutineHealthService(session).run_result(run(w, 1))
            await session.commit()

    try:
        await asyncio.gather(report(), report())
        await db.refresh(w.parent)
        assert w.parent.consecutive_failures == 1 and w.parent.is_active
        assert await count(db) == 1
    finally:
        await db.rollback()
        async with factory() as cleanup:
            await cleanup.execute(delete(Organization).where(Organization.id == w.organization_id))
            await cleanup.execute(delete(User).where(User.id == w.user_id))
            await cleanup.commit()


async def test_health_metadata_export_is_owner_scoped_and_size_accounted(db: AsyncSession) -> None:
    from app.repositories import personal_data_repo
    from app.schemas.personal_data import RoutineHealthExport

    w = await world(db)
    await RoutineHealthService(db).run_result(run(w, 1))
    (observation,) = await personal_data_repo.routine_health_of(db, w.user_id)
    exported = RoutineHealthExport.model_validate(observation)
    assert not exported.healthy and exported.trigger_id == w.parent.id
    assert await personal_data_repo.routine_health_export_size(db, w.user_id) == 1024
    assert await personal_data_repo.routine_health_of(db, uuid4()) == []
    assert await personal_data_repo.routine_health_export_size(db, uuid4()) == 0


@pytest.mark.parametrize("invalid", ["parent", "limit", "count"])
async def test_database_rejects_invalid_health_state(db: AsyncSession, invalid: str) -> None:
    w = await world(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            if invalid == "parent":
                db.add(
                    RoutineHealthObservation(
                        organization_id=w.organization_id,
                        user_id=w.user_id,
                        activation_at=NOW,
                        healthy=False,
                    )
                )
            elif invalid == "limit":
                w.parent.max_failures = 21
            else:
                w.parent.consecutive_failures = -1
            await db.flush()
