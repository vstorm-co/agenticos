"""What the memory queries actually return, against Postgres (#1594).

Two things a mocked session cannot answer. Whether a suppressed note really stops
reaching the model - that is a `WHERE` clause, and the whole value of
"deactivated" rests on it. And whether one person's listing spans agents without
reaching another person's store, which is an `owner_key` filter and a tenant
filter working together.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory_keys import person_owner_key, room_owner_key
from app.db.models.agent import Agent
from app.db.models.memory import AgentMemoryFile
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import memory_repo

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _tenant(db: AsyncSession) -> tuple[Organization, User]:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
    )
    db.add(organization)
    await db.flush()
    return organization, user


async def _agent(db: AsyncSession, organization: Organization, user: User, name: str) -> Agent:
    agent = Agent(
        organization_id=organization.id,
        name=name,
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    return agent


async def _note(
    db: AsyncSession,
    organization: Organization,
    agent: Agent,
    owner_key: str,
    name: str,
    *,
    deactivated: bool = False,
) -> AgentMemoryFile:
    note = AgentMemoryFile(
        organization_id=organization.id,
        agent_id=agent.id,
        owner_key=owner_key,
        name=name,
        content="something",
        deactivated_at=datetime(2026, 9, 1, tzinfo=UTC) if deactivated else None,
    )
    db.add(note)
    await db.flush()
    return note


class TestWhatTheAgentSees:
    async def test_a_suppressed_note_is_not_listed(self, db: AsyncSession):
        """The whole of what "deactivated" has to mean to be worth offering."""
        organization, user = await _tenant(db)
        agent = await _agent(db, organization, user, "Support")
        owner = person_owner_key(user.id)
        await _note(db, organization, agent, owner, "kept")
        await _note(db, organization, agent, owner, "hidden", deactivated=True)

        rows = await memory_repo.list_for_owner(
            db, organization_id=organization.id, agent_id=agent.id, owner_key=owner
        )

        assert [row.name for row in rows] == ["kept"]

    async def test_a_suppressed_note_is_not_read_back_by_name(self, db: AsyncSession):
        """Not listed but still readable by a name the model remembers would be a
        suppression that suppressed nothing."""
        organization, user = await _tenant(db)
        agent = await _agent(db, organization, user, "Support")
        owner = person_owner_key(user.id)
        await _note(db, organization, agent, owner, "hidden", deactivated=True)

        found = await memory_repo.get_by_name(
            db,
            organization_id=organization.id,
            agent_id=agent.id,
            owner_key=owner,
            name="hidden",
        )

        assert found is None

    async def test_the_write_path_still_sees_it_because_the_name_is_taken(self, db: AsyncSession):
        """The unique constraint does not care that a row is suppressed, so a
        create that could not see it would fail with nothing useful to say."""
        organization, user = await _tenant(db)
        agent = await _agent(db, organization, user, "Support")
        owner = person_owner_key(user.id)
        await _note(db, organization, agent, owner, "hidden", deactivated=True)

        found = await memory_repo.get_by_name(
            db,
            organization_id=organization.id,
            agent_id=agent.id,
            owner_key=owner,
            name="hidden",
            include_deactivated=True,
        )

        assert found is not None


class TestWhatThePersonSees:
    async def test_their_listing_spans_every_agent(self, db: AsyncSession):
        """ "What is written down about me here" is not a per-agent question, and
        answering it agent by agent makes somebody hunt."""
        organization, user = await _tenant(db)
        owner = person_owner_key(user.id)
        for name in ("Support", "Research"):
            agent = await _agent(db, organization, user, name)
            await _note(db, organization, agent, owner, f"from-{name}")

        rows, total = await memory_repo.list_for_person(
            db, organization_id=organization.id, owner_key=owner
        )

        assert total == 2
        assert {row.name for row in rows} == {"from-Support", "from-Research"}

    async def test_their_listing_includes_what_they_suppressed(self, db: AsyncSession):
        organization, user = await _tenant(db)
        agent = await _agent(db, organization, user, "Support")
        owner = person_owner_key(user.id)
        await _note(db, organization, agent, owner, "hidden", deactivated=True)

        rows, total = await memory_repo.list_for_person(
            db, organization_id=organization.id, owner_key=owner
        )

        assert total == 1
        assert rows[0].deactivated_at is not None

    async def test_it_reaches_neither_a_colleagues_store_nor_a_rooms(self, db: AsyncSession):
        """Something written down alone with somebody is not read back aloud, and
        a colleague's notes are not the caller's to see at all."""
        organization, user = await _tenant(db)
        agent = await _agent(db, organization, user, "Support")
        colleague = uuid.uuid4()
        await _note(db, organization, agent, person_owner_key(user.id), "mine")
        await _note(db, organization, agent, person_owner_key(colleague), "theirs")
        await _note(db, organization, agent, room_owner_key("slack", "C1"), "the-rooms")

        rows, total = await memory_repo.list_for_person(
            db, organization_id=organization.id, owner_key=person_owner_key(user.id)
        )

        assert total == 1
        assert rows[0].name == "mine"

    async def test_another_tenants_rows_are_not_in_it(self, db: AsyncSession):
        mine, me = await _tenant(db)
        theirs, them = await _tenant(db)
        my_agent = await _agent(db, mine, me, "Support")
        their_agent = await _agent(db, theirs, them, "Support")
        await _note(db, mine, my_agent, person_owner_key(me.id), "mine")
        await _note(db, theirs, their_agent, person_owner_key(me.id), "planted")

        rows, total = await memory_repo.list_for_person(
            db, organization_id=mine.id, owner_key=person_owner_key(me.id)
        )

        assert total == 1
        assert rows[0].name == "mine"

    async def test_a_note_is_reachable_by_id_only_from_its_own_store(self, db: AsyncSession):
        """The owner is part of the lookup rather than checked afterwards."""
        organization, user = await _tenant(db)
        agent = await _agent(db, organization, user, "Support")
        colleague = uuid.uuid4()
        theirs = await _note(db, organization, agent, person_owner_key(colleague), "theirs")

        found = await memory_repo.get_owned(
            db,
            organization_id=organization.id,
            owner_key=person_owner_key(user.id),
            file_id=theirs.id,
        )

        assert found is None
