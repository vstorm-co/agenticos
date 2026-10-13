"""Seeding system agents where the database cannot stage the failure.

The integration suite proves what a seed writes. These are the refusals no real
database produces on demand: the deployment's agent ceiling, a publish refused
after the agent was created, and two requests seeding the same agent at once.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.agents.system_agents import JUDGE, SYSTEM_AGENTS, system_agent
from app.core.exceptions import BadRequestError, SystemAgentUnavailableError
from app.repositories import agent_repo, credential_repo, member_repo
from app.services.system_agents import SystemAgentService

pytestmark = pytest.mark.anyio


def _service(monkeypatch, *, profile=None, owner=None) -> SystemAgentService:
    db = AsyncMock()
    savepoint = MagicMock()
    savepoint.__aenter__ = AsyncMock()
    savepoint.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=savepoint)
    service = SystemAgentService(db)
    monkeypatch.setattr(agent_repo, "get_system", AsyncMock(return_value=None))
    monkeypatch.setattr(credential_repo, "oldest_profile", AsyncMock(return_value=profile))
    monkeypatch.setattr(
        member_repo, "first_owner_id", AsyncMock(return_value=owner or uuid.uuid4())
    )
    return service


def test_every_registered_definition_is_found_by_its_key() -> None:
    assert [system_agent(definition.key) for definition in SYSTEM_AGENTS] == list(SYSTEM_AGENTS)


def test_an_unregistered_key_is_a_programming_error() -> None:
    with pytest.raises(KeyError):
        system_agent("nobody")


async def test_a_seed_the_ceiling_refuses_does_not_refuse_the_organization(monkeypatch) -> None:
    service = _service(monkeypatch)
    service.registry.create = AsyncMock(side_effect=BadRequestError(message="ceiling"))

    await service.seed(organization_id=uuid.uuid4(), owner_id=uuid.uuid4())

    service.registry.create.assert_awaited()


async def test_ensure_past_the_ceiling_says_the_agent_could_not_be_set_up(monkeypatch) -> None:
    service = _service(monkeypatch)
    service.registry.create = AsyncMock(
        side_effect=BadRequestError(message="This deployment allows 5 agents")
    )

    with pytest.raises(SystemAgentUnavailableError) as raised:
        await service.ensure(organization_id=uuid.uuid4(), key=JUDGE.key)

    assert raised.value.reason == "not_seeded"
    assert "5 agents" in raised.value.message


async def test_a_refused_publish_leaves_the_agent_a_draft(monkeypatch) -> None:
    service = _service(monkeypatch, profile=MagicMock(id=uuid.uuid4()))
    agent = MagicMock(id=uuid.uuid4())
    monkeypatch.setattr(service, "_insert", AsyncMock(return_value=agent))
    service.registry.publish = AsyncMock(side_effect=BadRequestError(message="no key"))

    seeded = await service.ensure(organization_id=uuid.uuid4(), key=JUDGE.key)

    assert seeded is agent


async def test_a_concurrent_seed_returns_the_row_that_won(monkeypatch) -> None:
    service = _service(monkeypatch)
    winner = MagicMock(id=uuid.uuid4())
    monkeypatch.setattr(
        service, "_insert", AsyncMock(side_effect=IntegrityError("insert", {}, Exception()))
    )
    monkeypatch.setattr(agent_repo, "get_system", AsyncMock(side_effect=[None, winner]))

    assert await service.ensure(organization_id=uuid.uuid4(), key=JUDGE.key) is winner


async def test_an_integrity_error_with_no_winner_is_not_swallowed(monkeypatch) -> None:
    service = _service(monkeypatch)
    monkeypatch.setattr(
        service, "_insert", AsyncMock(side_effect=IntegrityError("insert", {}, Exception()))
    )

    with pytest.raises(IntegrityError):
        await service.ensure(organization_id=uuid.uuid4(), key=JUDGE.key)
