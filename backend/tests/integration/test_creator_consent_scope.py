"""A new version withdraws "run as me" only where it reaches (#3290).

A creator who let a routine act as them agreed to the version it ran then, so
another person's publish, rollback or promotion that puts a new version in front
of it switches the consent off - and with it the routine's source consent, which
names the flag. A routine whose environment the version does not reach goes on
running what its creator agreed to, so it keeps both and keeps running.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_trigger import AgentTrigger
from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_registry import AgentRegistryService
from app.services.routine_sources import RoutineSourceService, RoutineSourcesRequired
from tests.integration.test_eval_suites import (
    _agent,
    _dataset,
    _environment,
    _member,
    _owner,
)
from tests.integration.test_promotion_gate import _guarded, _published

pytestmark = [pytest.mark.anyio, pytest.mark.security]

# No real model or dispatch: the fixture publishing needs, collected from here.
__all__ = ["_environment"]


async def _routine(
    db: AsyncSession, creator: AuthContext, agent: Agent, environment_id: uuid.UUID | None
) -> AgentTrigger:
    """A routine `creator` made to act as them, with its sources reviewed."""
    trigger = AgentTrigger(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        created_by_user_id=creator.user_id,
        environment_id=environment_id,
        prompt="Morning report",
        interval_seconds=3600,
        next_fire_at=datetime.now(UTC),
        runs_as_creator=True,
    )
    db.add(trigger)
    await db.flush()
    policy = await RoutineSourceService(db).initial(creator, trigger)
    trigger.approved_sources = policy.model_dump(mode="json")
    await db.flush()
    return trigger


async def _still_runs(db: AsyncSession, creator: AuthContext, trigger: AgentTrigger) -> bool:
    """Whether the routine's reviewed sources still admit its next fire."""
    await db.refresh(trigger)
    policy = RoutineSourceService(db)
    try:
        await policy.require_current(
            creator, trigger, expected_id=uuid.UUID(trigger.approved_sources["id"])
        )
    except RoutineSourcesRequired:
        return False
    return True


async def _split(db: AsyncSession, publisher: AuthContext, agent: Agent):
    """`production` pinned where it is, and a `dev` that follows every publish."""
    environments = AgentEnvironmentService(db)
    [production] = await environments.list_for_agent(publisher, agent.id)
    await environments.update(
        publisher, agent.id, production.id, EnvironmentUpdate(tracks_latest=False)
    )
    dev = await environments.create(
        publisher, agent.id, EnvironmentCreate(name="dev", tracks_latest=True)
    )
    return production, dev


async def _following(db: AsyncSession, publisher: AuthContext, agent: Agent) -> None:
    """The default following publishes, as a first publish leaves it."""
    environments = AgentEnvironmentService(db)
    [production] = await environments.list_for_agent(publisher, agent.id)
    await environments.update(
        publisher, agent.id, production.id, EnvironmentUpdate(tracks_latest=True)
    )


async def _people(db: AsyncSession) -> tuple[AuthContext, AuthContext]:
    publisher = await _owner(db)
    creator = await _member(db, publisher, OrgRoleName.ADMIN)
    return publisher, creator


async def test_a_publish_that_leaves_production_alone_leaves_its_routines_running(db):
    publisher, creator = await _people(db)
    agent, _ = await _agent(db, publisher)
    production, dev = await _split(db, publisher, agent)
    on_production = await _routine(db, creator, agent, production.id)
    unscoped = await _routine(db, creator, agent, None)
    on_dev = await _routine(db, creator, agent, dev.id)

    await _published(db, publisher, agent)

    assert await _still_runs(db, creator, on_production)
    assert await _still_runs(db, creator, unscoped)
    assert on_production.runs_as_creator and unscoped.runs_as_creator
    # The version reached dev, so the consent given to the old one ends there.
    assert not await _still_runs(db, creator, on_dev)
    assert on_dev.runs_as_creator is False


async def test_a_publish_that_moves_the_default_withdraws_from_routines_naming_none(db):
    publisher, creator = await _people(db)
    agent, _ = await _agent(db, publisher)
    await _following(db, publisher, agent)
    unscoped = await _routine(db, creator, agent, None)

    await _published(db, publisher, agent)

    assert not await _still_runs(db, creator, unscoped)
    assert unscoped.runs_as_creator is False


async def test_the_publishers_own_routine_keeps_its_consent(db):
    publisher, _ = await _people(db)
    agent, _ = await _agent(db, publisher)
    await _following(db, publisher, agent)
    own = await _routine(db, publisher, agent, None)

    await _published(db, publisher, agent)

    assert await _still_runs(db, publisher, own)
    assert own.runs_as_creator is True


async def test_a_rollback_withdraws_only_where_it_lands(db):
    publisher, creator = await _people(db)
    agent, first = await _agent(db, publisher)
    production, dev = await _split(db, publisher, agent)
    await _published(db, publisher, agent)
    on_production = await _routine(db, creator, agent, production.id)
    on_dev = await _routine(db, creator, agent, dev.id)

    await AgentRegistryService(db).rollback(publisher, agent.id, to_version_id=first.id)

    assert await _still_runs(db, creator, on_production)
    assert not await _still_runs(db, creator, on_dev)


async def test_a_promotion_withdraws_from_that_environment_alone(db):
    publisher, creator = await _people(db)
    agent, _ = await _agent(db, publisher)
    production, dev = await _split(db, publisher, agent)
    newer = await _published(db, publisher, agent)
    on_production = await _routine(db, creator, agent, production.id)
    on_dev = await _routine(db, creator, agent, dev.id)
    environments = AgentEnvironmentService(db)

    # Already there: putting dev on the version it serves changes nothing it runs.
    await environments.update(publisher, agent.id, dev.id, EnvironmentUpdate(version_id=newer.id))
    assert await _still_runs(db, creator, on_dev)

    await environments.update(
        publisher, agent.id, production.id, EnvironmentUpdate(version_id=newer.id)
    )

    assert not await _still_runs(db, creator, on_production)
    assert await _still_runs(db, creator, on_dev)


async def test_a_guarded_follower_loses_it_at_the_publish_it_will_move_to(db):
    """It moves later, when its guards pass, and that move withdraws nothing - so the
    publish that mints the version it is headed for has to."""
    publisher, creator = await _people(db)
    agent, first = await _agent(db, publisher)
    production, _ = await _split(db, publisher, agent)
    staging_id, _ = await _guarded(
        db, publisher, agent, first, await _dataset(db, publisher), tracks_latest=True
    )
    on_staging = await _routine(db, creator, agent, staging_id)
    on_production = await _routine(db, creator, agent, production.id)

    await _published(db, publisher, agent)

    assert not await _still_runs(db, creator, on_staging)
    assert await _still_runs(db, creator, on_production)


async def test_an_impersonated_publish_keeps_nobodys_consent(db, monkeypatch):
    """An administrator acting as the creator is somebody else's publish."""
    publisher, _ = await _people(db)
    agent, _ = await _agent(db, publisher)
    await _following(db, publisher, agent)
    own = await _routine(db, publisher, agent, None)
    monkeypatch.setattr("app.services.agent_registry.current_impersonator", uuid.uuid4)

    await _published(db, publisher, agent)

    assert not await _still_runs(db, publisher, own)
