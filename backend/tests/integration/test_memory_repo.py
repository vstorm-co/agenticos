"""Guarantees the agent-memory-files table makes that only a database can.

Three of them are load-bearing. A name is unique *within one owner's store* and
free everywhere else, which is what lets every person have their own `MEMORY.md`.
Reads are scoped to the organization and to one owner, so neither another tenant's
notes nor another person's can reach a run. And deleting an agent takes its memory
with it, because a store whose agent is gone is rows nobody can ever reach or
erase.

`owner_key` is `NOT NULL` now, so the `NULLS NOT DISTINCT` the organisation-wide
store needed is gone with it - as is the `origin` column and the trust tier it
carried. Both went with the store that made them necessary (#1470).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.memory_keys import person_owner_key, room_owner_key
from app.db.models.agent import Agent
from app.db.models.memory import AgentMemoryFile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import memory_repo

pytestmark = pytest.mark.anyio

ANNA = person_owner_key(uuid.uuid4())
BEN = person_owner_key(uuid.uuid4())
ROOM = room_owner_key("slack", "C1")


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, *, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org


async def _agent(db, *, org: Organization) -> Agent:
    agent = Agent(
        id=uuid.uuid4(), organization_id=org.id, slug=f"a-{uuid.uuid4().hex[:8]}", name="Support"
    )
    db.add(agent)
    await db.flush()
    return agent


async def _create(db, *, agent, owner_key, name, content="body", kind="note"):
    return await memory_repo.create(
        db,
        organization_id=agent.organization_id,
        agent_id=agent.id,
        owner_key=owner_key,
        name=name,
        description=None,
        content=content,
        content_format="md",
        kind=kind,
    )


async def _fresh_agent(db) -> Agent:
    return await _agent(db, org=await _org(db, owner=await _user(db)))


class TestUniqueness:
    async def test_a_duplicate_name_in_one_store_is_refused(self, db) -> None:
        """Which is what makes `write_memory` able to report a taken name rather
        than silently overwrite a note - the tool checks, but the index is the
        guard that holds under two turns racing."""
        agent = await _fresh_agent(db)
        await _create(db, agent=agent, owner_key=ANNA, name="prefs")

        with pytest.raises(IntegrityError):
            await _create(db, agent=agent, owner_key=ANNA, name="prefs")

    async def test_two_people_may_each_have_a_note_of_the_same_name(self, db) -> None:
        """Every person's store has its own `MEMORY.md`; a global unique name would
        mean the first person to talk to an agent owned that name."""
        agent = await _fresh_agent(db)
        await _create(db, agent=agent, owner_key=ANNA, name="MEMORY.md")

        theirs = await _create(db, agent=agent, owner_key=BEN, name="MEMORY.md")

        assert theirs.owner_key == BEN

    async def test_a_room_and_a_person_do_not_collide(self, db) -> None:
        agent = await _fresh_agent(db)
        await _create(db, agent=agent, owner_key=ANNA, name="prefs")

        theirs = await _create(db, agent=agent, owner_key=ROOM, name="prefs")

        assert theirs.owner_key == ROOM

    async def test_one_name_across_two_agents_is_allowed(self, db) -> None:
        """Memory is the agent's own, so two agents talking to one person keep
        separate notes under the same name."""
        org = await _org(db, owner=await _user(db))
        first, second = await _agent(db, org=org), await _agent(db, org=org)
        await _create(db, agent=first, owner_key=ANNA, name="prefs")

        other = await _create(db, agent=second, owner_key=ANNA, name="prefs")

        assert other.agent_id == second.id

    async def test_a_note_belonging_to_nobody_is_refused(self, db) -> None:
        """`owner_key` is `NOT NULL`: every note belongs to a person or a room, and
        the organisation-wide store that made a null meaningful is gone."""
        agent = await _fresh_agent(db)

        with pytest.raises(IntegrityError):
            await _create(db, agent=agent, owner_key=None, name="prefs")


class TestReads:
    async def test_one_store_is_read_and_never_another(self, db) -> None:
        """The cross-person guarantee, at the query. Anything wider here would be
        read into a conversation somebody else is having."""
        agent = await _fresh_agent(db)
        await _create(db, agent=agent, owner_key=ANNA, name="mine")
        await _create(db, agent=agent, owner_key=BEN, name="theirs")

        rows = await memory_repo.list_for_owner(
            db, organization_id=agent.organization_id, agent_id=agent.id, owner_key=ANNA
        )

        assert [row.name for row in rows] == ["mine"]

    async def test_another_tenants_note_is_not_reachable_by_name(self, db) -> None:
        """The organization is on the query even though the agent id alone would
        already be unique - a wrong id must answer nothing rather than answer."""
        theirs = await _fresh_agent(db)
        await _create(db, agent=theirs, owner_key=ANNA, name="prefs")
        ours = await _fresh_agent(db)

        found = await memory_repo.get_by_name(
            db,
            organization_id=ours.organization_id,
            agent_id=theirs.id,
            owner_key=ANNA,
            name="prefs",
        )

        assert found is None

    async def test_the_listing_is_newest_first(self, db) -> None:
        """A long-lived store hands the model what it learned last rather than
        whatever sorts first alphabetically."""
        agent = await _fresh_agent(db)
        first = await _create(db, agent=agent, owner_key=ANNA, name="aaa")
        await _create(db, agent=agent, owner_key=ANNA, name="zzz")
        await memory_repo.update(db, file=first, update_data={"content": "edited"})

        rows = await memory_repo.list_for_owner(
            db, organization_id=agent.organization_id, agent_id=agent.id, owner_key=ANNA
        )

        assert [row.name for row in rows] == ["aaa", "zzz"]

    async def test_the_listing_stops_at_its_cap(self, db) -> None:
        agent = await _fresh_agent(db)
        for index in range(5):
            await _create(db, agent=agent, owner_key=ANNA, name=f"note-{index}")

        rows = await memory_repo.list_for_owner(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            owner_key=ANNA,
            limit=2,
        )

        assert len(rows) == 2


class TestDeleting:
    async def test_deleting_the_agent_takes_its_memory(self, db) -> None:
        """`ondelete="CASCADE"`. Rows whose agent is gone are rows nobody can reach
        through any tool and nobody can erase through any route."""
        agent = await _fresh_agent(db)
        await _create(db, agent=agent, owner_key=ANNA, name="prefs")

        await db.delete(agent)
        await db.flush()

        left = (
            (await db.execute(select(AgentMemoryFile).where(AgentMemoryFile.agent_id == agent.id)))
            .scalars()
            .all()
        )
        assert left == []

    async def test_clearing_an_agent_empties_every_store_it_holds(self, db) -> None:
        agent = await _fresh_agent(db)
        await _create(db, agent=agent, owner_key=ANNA, name="prefs")
        await _create(db, agent=agent, owner_key=ROOM, name="prefs")

        removed = await memory_repo.delete_all_for_agent(
            db, organization_id=agent.organization_id, agent_id=agent.id
        )

        assert removed == 2

    async def test_clearing_one_agent_leaves_the_others_alone(self, db) -> None:
        org = await _org(db, owner=await _user(db))
        cleared, kept = await _agent(db, org=org), await _agent(db, org=org)
        await _create(db, agent=cleared, owner_key=ANNA, name="prefs")
        await _create(db, agent=kept, owner_key=ANNA, name="prefs")

        await memory_repo.delete_all_for_agent(db, organization_id=org.id, agent_id=cleared.id)

        rows = await memory_repo.list_for_owner(
            db, organization_id=org.id, agent_id=kept.id, owner_key=ANNA
        )
        assert [row.name for row in rows] == ["prefs"]

    async def test_forgetting_a_person_spans_every_agent_in_the_organization(self, db) -> None:
        """ "Forget everything you know about me" is a fact about a person, not
        about one agent they happened to talk to - answering it agent by agent is
        how a deletion request ends up half-done."""
        org = await _org(db, owner=await _user(db))
        first, second = await _agent(db, org=org), await _agent(db, org=org)
        await _create(db, agent=first, owner_key=ANNA, name="prefs")
        await _create(db, agent=second, owner_key=ANNA, name="prefs")

        removed = await memory_repo.delete_for_person(db, organization_id=org.id, owner_key=ANNA)

        assert removed == 2

    async def test_forgetting_a_person_leaves_everybody_else(self, db) -> None:
        agent = await _fresh_agent(db)
        await _create(db, agent=agent, owner_key=ANNA, name="prefs")
        await _create(db, agent=agent, owner_key=BEN, name="prefs")

        await memory_repo.delete_for_person(
            db, organization_id=agent.organization_id, owner_key=ANNA
        )

        rows = await memory_repo.list_for_owner(
            db, organization_id=agent.organization_id, agent_id=agent.id, owner_key=BEN
        )
        assert [row.name for row in rows] == ["prefs"]

    async def test_forgetting_a_person_never_empties_a_room(self, db) -> None:
        """A room's notes are a colleague's as much as they are this person's. The
        prefix is asserted rather than trusted, because the caller that passes the
        wrong key would otherwise erase a channel a dozen people write to."""
        agent = await _fresh_agent(db)
        await _create(db, agent=agent, owner_key=ROOM, name="prefs")

        with pytest.raises(ValueError, match="not a person store"):
            await memory_repo.delete_for_person(
                db, organization_id=agent.organization_id, owner_key=ROOM
            )

        rows = await memory_repo.list_for_owner(
            db, organization_id=agent.organization_id, agent_id=agent.id, owner_key=ROOM
        )
        assert [row.name for row in rows] == ["prefs"]

    async def test_forgetting_a_person_stops_at_the_organization(self, db) -> None:
        """One person can be a member of two organizations, and erasing themselves
        in one must not reach into the other."""
        here = await _fresh_agent(db)
        elsewhere = await _fresh_agent(db)
        await _create(db, agent=here, owner_key=ANNA, name="prefs")
        await _create(db, agent=elsewhere, owner_key=ANNA, name="prefs")

        removed = await memory_repo.delete_for_person(
            db, organization_id=here.organization_id, owner_key=ANNA
        )

        assert removed == 1

    async def test_deleting_one_note_leaves_the_rest(self, db) -> None:
        agent = await _fresh_agent(db)
        note = await _create(db, agent=agent, owner_key=ANNA, name="prefs")
        await _create(db, agent=agent, owner_key=ANNA, name="MEMORY.md")

        await memory_repo.delete(db, note)

        rows = await memory_repo.list_for_owner(
            db, organization_id=agent.organization_id, agent_id=agent.id, owner_key=ANNA
        )
        assert [row.name for row in rows] == ["MEMORY.md"]
