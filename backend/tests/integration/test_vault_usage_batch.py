"""Which agents bind each secret, resolved for a whole page in one query (#953).

The vault listing used to ask this once per secret. Batched, it is one grouped
JSONB read - which only a real database exercises: the query unnests each agent's
draft-spec capabilities and matches the bound `secret_id`, and the guard that
keeps `jsonb_array_elements` off a spec whose `capabilities` is not an array is
exactly the kind of thing a mock cannot show.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.db.models.agent import Agent
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import organization_secret as organization_secret_repo

pytestmark = pytest.mark.anyio


async def _org(db: Any) -> Organization:
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
    return org


async def _agent(db: Any, org: Organization, *, name: str, capabilities: Any) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        name=name,
        draft_spec={"capabilities": capabilities} if capabilities is not None else {},
    )
    db.add(agent)
    await db.flush()
    return agent


def _binds(*secret_ids: uuid.UUID) -> list[dict[str, str]]:
    return [{"key": "knowledge", "secret_id": str(s)} for s in secret_ids]


async def test_it_groups_agents_by_the_secret_their_draft_binds(db: Any) -> None:
    org = await _org(db)
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    beta = await _agent(db, org, name="Beta", capabilities=_binds(s1, s2))
    alfa = await _agent(db, org, name="Alfa", capabilities=_binds(s1))

    usage = await organization_secret_repo.agents_using_for_secrets(
        db, organization_id=org.id, secret_ids=[s1, s2, s3]
    )

    # Name order, and every requested id is a key - one nothing binds included.
    assert usage[s1] == [(alfa.id, "Alfa"), (beta.id, "Beta")]
    assert usage[s2] == [(beta.id, "Beta")]
    assert usage[s3] == []


async def test_an_agent_in_another_organization_is_not_counted(db: Any) -> None:
    org = await _org(db)
    other = await _org(db)
    secret = uuid.uuid4()
    mine = await _agent(db, org, name="Mine", capabilities=_binds(secret))
    await _agent(db, other, name="Theirs", capabilities=_binds(secret))

    usage = await organization_secret_repo.agents_using_for_secrets(
        db, organization_id=org.id, secret_ids=[secret]
    )

    assert usage[secret] == [(mine.id, "Mine")]


async def test_a_spec_whose_capabilities_are_not_a_list_is_skipped(db: Any) -> None:
    """`jsonb_array_elements` errors on a non-array; the query's `CASE` guard
    hands it an empty one instead, so these agents are simply absent."""
    org = await _org(db)
    secret = uuid.uuid4()
    binder = await _agent(db, org, name="Binder", capabilities=_binds(secret))
    await _agent(db, org, name="NoCapsKey", capabilities=None)
    await _agent(db, org, name="CapsNotAList", capabilities={"not": "a list"})

    usage = await organization_secret_repo.agents_using_for_secrets(
        db, organization_id=org.id, secret_ids=[secret]
    )

    assert usage[secret] == [(binder.id, "Binder")]


async def test_the_same_secret_bound_twice_counts_the_agent_once(db: Any) -> None:
    org = await _org(db)
    secret = uuid.uuid4()
    agent = await _agent(
        db,
        org,
        name="Twice",
        capabilities=[
            {"key": "knowledge", "secret_id": str(secret)},
            {"key": "mcp", "secret_id": str(secret)},
        ],
    )

    usage = await organization_secret_repo.agents_using_for_secrets(
        db, organization_id=org.id, secret_ids=[secret]
    )

    assert usage[secret] == [(agent.id, "Twice")]


async def test_no_secret_ids_asks_nothing(db: Any) -> None:
    org = await _org(db)
    assert (
        await organization_secret_repo.agents_using_for_secrets(
            db, organization_id=org.id, secret_ids=[]
        )
        == {}
    )
