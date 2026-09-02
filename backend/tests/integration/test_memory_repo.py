"""Guarantees the agent-memory-files table makes that only a database can.

The load-bearing ones: a name is unique *within a partition*, and because the
shared partition is a `NULL` key that has to mean "the one shared store", the
constraint is `NULLS NOT DISTINCT` - two shared files with one name collide,
which a plain SQL `NULL` would not catch. The `origin` CHECK refuses a value the
trust tier cannot branch on. Reads are scoped to the organization (cross-tenant)
and union the shared store with one person's, never another's (cross-user);
deleting the agent takes its memory.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.models.agent import Agent
from app.db.models.memory import AgentMemoryFact, AgentMemoryFile, MemoryOrigin
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import memory_repo

pytestmark = pytest.mark.anyio

AGENT = MemoryOrigin.AGENT.value


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


async def _create(db, *, agent, scope_key, name, origin=AGENT, content="body", kind="note"):
    return await memory_repo.create(
        db,
        organization_id=agent.organization_id,
        agent_id=agent.id,
        end_user_scope_key=scope_key,
        name=name,
        description=None,
        content=content,
        content_format="md",
        kind=kind,
        origin=origin,
    )


class TestUniqueness:
    async def test_two_shared_files_with_one_name_collide_nulls_not_distinct(self, db) -> None:
        """The whole reason for NULLS NOT DISTINCT: two NULL scopes are the same store."""
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        await _create(db, agent=agent, scope_key=None, name="prefs")
        with pytest.raises(IntegrityError):
            await _create(db, agent=agent, scope_key=None, name="prefs")

    async def test_one_name_in_two_partitions_is_allowed(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        await _create(db, agent=agent, scope_key=None, name="prefs")
        both = await _create(db, agent=agent, scope_key="user:1", name="prefs")
        assert both.name == "prefs"

    async def test_a_duplicate_in_one_per_user_partition_is_refused(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        await _create(db, agent=agent, scope_key="user:1", name="prefs")
        with pytest.raises(IntegrityError):
            await _create(db, agent=agent, scope_key="user:1", name="prefs")

    async def test_one_name_across_two_agents_is_allowed(self, db) -> None:
        person = await _user(db)
        org = await _org(db, owner=person)
        first, second = await _agent(db, org=org), await _agent(db, org=org)
        await _create(db, agent=first, scope_key=None, name="prefs")
        other = await _create(db, agent=second, scope_key=None, name="prefs")
        assert other.agent_id == second.id


class TestOriginCheck:
    async def test_an_unknown_origin_is_refused_by_the_check(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        with pytest.raises(IntegrityError):
            await _create(db, agent=agent, scope_key=None, name="prefs", origin="somewhere")


class TestScoping:
    async def test_get_is_scoped_to_the_organization(self, db) -> None:
        person = await _user(db)
        org = await _org(db, owner=person)
        other_org = await _org(db, owner=person)
        agent = await _agent(db, org=org)
        file = await _create(db, agent=agent, scope_key=None, name="prefs")
        assert await memory_repo.get(db, file.id, organization_id=org.id) is not None
        assert await memory_repo.get(db, file.id, organization_id=other_org.id) is None

    async def test_get_by_name_is_scoped_to_the_partition(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        await _create(db, agent=agent, scope_key="user:1", name="prefs")
        found = await memory_repo.get_by_name(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            end_user_scope_key="user:1",
            name="prefs",
        )
        assert found is not None
        missing = await memory_repo.get_by_name(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            end_user_scope_key=None,
            name="prefs",
        )
        assert missing is None

    async def test_get_readable_by_name_prefers_the_personal_copy(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        await _create(db, agent=agent, scope_key=None, name="prefs", content="shared body")
        await _create(db, agent=agent, scope_key="user:1", name="prefs", content="personal body")

        # A name in both tiers resolves to the current person's own copy.
        personal = await memory_repo.get_readable_by_name(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            personal_key="user:1",
            name="prefs",
        )
        assert personal is not None and personal.content == "personal body"

        # With no person, only the shared copy is readable.
        shared = await memory_repo.get_readable_by_name(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            personal_key=None,
            name="prefs",
        )
        assert shared is not None and shared.content == "shared body"

    async def test_list_readable_unions_shared_and_the_person_and_isolates_others(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        await _create(db, agent=agent, scope_key=None, name="company")
        await _create(db, agent=agent, scope_key="user:a", name="a-note")
        await _create(db, agent=agent, scope_key="user:b", name="b-note")

        for_a = await memory_repo.list_readable(
            db, organization_id=agent.organization_id, agent_id=agent.id, personal_key="user:a"
        )
        # Shared plus user:a's own - never user:b's.
        assert {row.name for row in for_a} == {"company", "a-note"}

        anonymous = await memory_repo.list_readable(
            db, organization_id=agent.organization_id, agent_id=agent.id, personal_key=None
        )
        assert {row.name for row in anonymous} == {"company"}

    async def test_list_readable_respects_the_limit(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        for i in range(3):
            await _create(db, agent=agent, scope_key=None, name=f"n{i}")
        capped = await memory_repo.list_readable(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            personal_key=None,
            limit=2,
        )
        assert len(capped) == 2


class TestListForAgent:
    async def test_all_partitions_versus_one_and_search_and_sort(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        await _create(db, agent=agent, scope_key=None, name="alpha")
        await _create(db, agent=agent, scope_key="user:1", name="beta")

        every, total = await memory_repo.list_for_agent(
            db, organization_id=agent.organization_id, agent_id=agent.id, all_partitions=True
        )
        assert {row.name for row in every} == {"alpha", "beta"}
        assert total == 2

        shared_only, _ = await memory_repo.list_for_agent(
            db, organization_id=agent.organization_id, agent_id=agent.id, scope_key=None
        )
        assert {row.name for row in shared_only} == {"alpha"}

        hits, _ = await memory_repo.list_for_agent(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            all_partitions=True,
            search="lph",
        )
        assert {row.name for row in hits} == {"alpha"}

        by_update, _ = await memory_repo.list_for_agent(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            sort="updated",
            all_partitions=True,
        )
        assert {row.name for row in by_update} == {"alpha", "beta"}

    async def test_scoped_only_lists_every_per_user_partition_and_not_the_shared(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        await _create(db, agent=agent, scope_key=None, name="company")
        await _create(db, agent=agent, scope_key="user:1", name="alice")
        await _create(db, agent=agent, scope_key="chan:2", name="bob")

        scoped, total = await memory_repo.list_for_agent(
            db, organization_id=agent.organization_id, agent_id=agent.id, scoped_only=True
        )
        assert {row.name for row in scoped} == {"alice", "bob"}
        assert total == 2


class TestMutationAndCascade:
    async def test_update_and_delete(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        file = await _create(db, agent=agent, scope_key=None, name="prefs")
        updated = await memory_repo.update(db, file=file, update_data={"content": "new"})
        assert updated.content == "new"
        await memory_repo.delete(db, file)
        assert await memory_repo.get(db, file.id, organization_id=agent.organization_id) is None

    async def test_deleting_the_agent_takes_its_memory(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        file = await _create(db, agent=agent, scope_key=None, name="prefs")
        await db.delete(await db.get(Agent, agent.id))
        await db.flush()
        remaining = await db.scalar(select(AgentMemoryFile).where(AgentMemoryFile.id == file.id))
        assert remaining is None

    async def test_delete_all_files_clears_every_partition_and_counts(self, db) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        await _create(db, agent=agent, scope_key=None, name="shared")
        await _create(db, agent=agent, scope_key="user:1", name="private")

        removed = await memory_repo.delete_all_files(
            db, organization_id=agent.organization_id, agent_id=agent.id
        )
        assert removed == 2
        _, total = await memory_repo.list_for_agent(
            db, organization_id=agent.organization_id, agent_id=agent.id, all_partitions=True
        )
        assert total == 0

    async def test_delete_all_files_is_scoped_to_the_agent(self, db) -> None:
        person = await _user(db)
        org = await _org(db, owner=person)
        agent = await _agent(db, org=org)
        other = await _agent(db, org=org)
        await _create(db, agent=agent, scope_key=None, name="mine")
        kept = await _create(db, agent=other, scope_key=None, name="theirs")

        await memory_repo.delete_all_files(db, organization_id=org.id, agent_id=agent.id)
        assert await memory_repo.get(db, kept.id, organization_id=org.id) is not None


def test_repr_names_the_agent_and_origin() -> None:
    file = AgentMemoryFile(agent_id=uuid.uuid4(), name="prefs", origin=AGENT)
    assert "prefs" in repr(file)
    assert "agent" in repr(file)


def test_fact_repr_names_the_agent() -> None:
    fact = AgentMemoryFact(agent_id=uuid.uuid4(), end_user_scope_key="user:1")
    assert "user:1" in repr(fact)


@pytest.fixture
async def facts_table(db) -> int:
    """The `embedding` column and extension migration 0064 adds in raw SQL.

    The integration schema is built with `create_all` from the models, and
    `AgentMemoryFact` deliberately omits the vector column, so a fact test adds
    what the migration would. No HNSW index: a handful of rows are found by a
    sequential scan, and the index is a performance concern the migration owns.
    Returns the embedding width so a test can build vectors of the right size.
    """
    dim = settings.rag.embeddings_config.dim
    await db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await db.execute(
        text(f"ALTER TABLE agent_memory_facts ADD COLUMN IF NOT EXISTS embedding vector({dim})")
    )
    await db.flush()
    return dim


def _unit_vector(dim: int, index: int) -> list[float]:
    vec = [0.0] * dim
    vec[index] = 1.0
    return vec


async def _add_fact(db, agent, *, content: str, at: int, dim: int, scope_key: str | None = None):
    await memory_repo.create_fact(
        db,
        organization_id=agent.organization_id,
        agent_id=agent.id,
        end_user_scope_key=scope_key,
        content=content,
        embedding=_unit_vector(dim, at),
    )


class TestFacts:
    async def test_recall_ranks_the_nearest_fact_first(self, db, facts_table) -> None:
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        await _add_fact(db, agent, content="likes tea", at=0, dim=facts_table)
        await _add_fact(db, agent, content="lives in Berlin", at=1, dim=facts_table)
        hits = await memory_repo.recall_facts(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            personal_key=None,
            query_embedding=_unit_vector(facts_table, 0),
            limit=5,
        )
        assert [hit.content for hit in hits] == ["likes tea", "lives in Berlin"]
        assert hits[0].score > hits[1].score

    async def test_recall_unions_shared_and_the_person_and_isolates_others(
        self, db, facts_table
    ) -> None:
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        await _add_fact(db, agent, content="company fact", at=0, dim=facts_table)
        await _add_fact(db, agent, content="a-secret", at=1, dim=facts_table, scope_key="user:a")
        await _add_fact(db, agent, content="b-secret", at=2, dim=facts_table, scope_key="user:b")
        for_a = await memory_repo.recall_facts(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            personal_key="user:a",
            query_embedding=_unit_vector(facts_table, 1),
            limit=5,
        )
        names = {hit.content for hit in for_a}
        assert "a-secret" in names  # the person's own
        assert "company fact" in names  # and the shared store
        assert "b-secret" not in names  # never another person's

    async def test_recall_isolates_organizations(self, db, facts_table) -> None:
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        other = await _agent(db, org=await _org(db, owner=person))
        await _add_fact(db, agent, content="mine", at=0, dim=facts_table)
        hits = await memory_repo.recall_facts(
            db,
            organization_id=other.organization_id,
            agent_id=other.id,
            personal_key=None,
            query_embedding=_unit_vector(facts_table, 0),
            limit=5,
        )
        assert hits == []

    async def test_list_facts_filters_by_substring_and_partition(self, db, facts_table) -> None:
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        await _add_fact(db, agent, content="likes green tea", at=0, dim=facts_table)
        await _add_fact(
            db, agent, content="prefers coffee", at=1, dim=facts_table, scope_key="user:1"
        )
        shared, total = await memory_repo.list_facts(
            db, organization_id=agent.organization_id, agent_id=agent.id, scope_key=None
        )
        assert {fact.content for fact in shared} == {"likes green tea"}
        assert total == 1
        hits, _ = await memory_repo.list_facts(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            all_partitions=True,
            search="coffee",
        )
        assert {fact.content for fact in hits} == {"prefers coffee"}

    async def test_facts_scoped_only_lists_the_per_user_partitions(self, db, facts_table) -> None:
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        await _add_fact(db, agent, content="company fact", at=0, dim=facts_table)
        await _add_fact(
            db, agent, content="private fact", at=1, dim=facts_table, scope_key="user:1"
        )
        scoped, total = await memory_repo.list_facts(
            db, organization_id=agent.organization_id, agent_id=agent.id, scoped_only=True
        )
        assert {fact.content for fact in scoped} == {"private fact"}
        assert total == 1

    async def test_delete_all_facts_clears_every_partition_and_counts(
        self, db, facts_table
    ) -> None:
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        await _add_fact(db, agent, content="one", at=0, dim=facts_table)
        await _add_fact(db, agent, content="two", at=1, dim=facts_table, scope_key="user:1")

        removed = await memory_repo.delete_all_facts(
            db, organization_id=agent.organization_id, agent_id=agent.id
        )
        assert removed == 2
        _, total = await memory_repo.list_facts(
            db, organization_id=agent.organization_id, agent_id=agent.id, all_partitions=True
        )
        assert total == 0

    async def test_delete_all_facts_is_scoped_to_the_agent(self, db, facts_table) -> None:
        org = await _org(db, owner=await _user(db))
        agent = await _agent(db, org=org)
        other = await _agent(db, org=org)
        await _add_fact(db, agent, content="mine", at=0, dim=facts_table)
        await _add_fact(db, other, content="theirs", at=1, dim=facts_table)

        await memory_repo.delete_all_facts(db, organization_id=org.id, agent_id=agent.id)

        kept, total = await memory_repo.list_facts(
            db, organization_id=org.id, agent_id=other.id, all_partitions=True
        )
        assert {fact.content for fact in kept} == {"theirs"}
        assert total == 1

    async def test_get_and_delete_a_fact(self, db, facts_table) -> None:
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        await _add_fact(db, agent, content="a fact", at=0, dim=facts_table)
        listed, _ = await memory_repo.list_facts(
            db, organization_id=agent.organization_id, agent_id=agent.id, all_partitions=True
        )
        fact = listed[0]
        assert await memory_repo.get_fact(db, fact.id, organization_id=agent.organization_id)
        assert await memory_repo.get_fact(db, fact.id, organization_id=uuid.uuid4()) is None
        await memory_repo.delete_fact(db, fact)
        assert (
            await memory_repo.get_fact(db, fact.id, organization_id=agent.organization_id) is None
        )

    async def test_deleting_the_agent_takes_its_facts(self, db, facts_table) -> None:
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        await _add_fact(db, agent, content="x", at=0, dim=facts_table)
        await db.delete(await db.get(Agent, agent.id))
        await db.flush()
        remaining = await db.scalar(
            select(AgentMemoryFact).where(AgentMemoryFact.agent_id == agent.id)
        )
        assert remaining is None
