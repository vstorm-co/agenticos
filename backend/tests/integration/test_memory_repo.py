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

    async def test_a_repeated_name_orders_by_id_so_paging_is_stable(self, db) -> None:
        """One name across three partitions. Ordering by name alone leaves the tie
        for OFFSET/LIMIT to resolve however it likes, dropping or repeating a row
        between pages; the id tie-breaker gives it a total order."""
        person = await _user(db)
        agent = await _agent(db, org=await _org(db, owner=person))
        a = await _create(db, agent=agent, scope_key=None, name="prefs")
        b = await _create(db, agent=agent, scope_key="user:1", name="prefs")
        c = await _create(db, agent=agent, scope_key="user:2", name="prefs")

        rows, total = await memory_repo.list_for_agent(
            db, organization_id=agent.organization_id, agent_id=agent.id, all_partitions=True
        )
        assert total == 3
        # All three share the name, so id decides the order.
        assert [row.id for row in rows] == sorted([a.id, b.id, c.id])

        seen = []
        for skip in range(3):
            page, _ = await memory_repo.list_for_agent(
                db,
                organization_id=agent.organization_id,
                agent_id=agent.id,
                all_partitions=True,
                skip=skip,
                limit=1,
            )
            seen.append(page[0].id)
        assert sorted(seen) == sorted([a.id, b.id, c.id]), "each row once, none dropped or repeated"


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
    """The `embedding` column and extension migration 0072 adds in raw SQL.

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


async def _add_fact(
    db,
    agent,
    *,
    content: str,
    at: int,
    dim: int,
    scope_key: str | None = None,
    origin: str = MemoryOrigin.AGENT.value,
):
    await memory_repo.create_fact(
        db,
        organization_id=agent.organization_id,
        agent_id=agent.id,
        end_user_scope_key=scope_key,
        content=content,
        embedding=_unit_vector(dim, at),
        origin=origin,
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

    async def test_brief_injects_personal_and_operator_shared_never_agent_shared(
        self, db, facts_table
    ) -> None:
        # A person's own facts (any origin) and operator-authored shared ones; never an
        # agent-authored shared fact, which is user-influenced content bound for everyone.
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        op = MemoryOrigin.OPERATOR.value
        ag = MemoryOrigin.AGENT.value
        await _add_fact(db, agent, content="op-shared", at=0, dim=facts_table, origin=op)
        await _add_fact(db, agent, content="agent-shared", at=1, dim=facts_table, origin=ag)
        await _add_fact(db, agent, content="a-own", at=2, dim=facts_table, scope_key="user:a")
        await _add_fact(db, agent, content="b-own", at=3, dim=facts_table, scope_key="user:b")
        for_a = await memory_repo.list_brief_facts(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            personal_key="user:a",
            limit=30,
        )
        names = {fact.content for fact in for_a}
        assert "a-own" in names  # the person's own, whoever wrote it
        assert "op-shared" in names  # operator-authored shared - a person vouched for it
        assert "agent-shared" not in names  # agent-authored shared - recall-only
        assert "b-own" not in names  # never another person's

    async def test_brief_is_newest_first_and_capped(self, db, facts_table) -> None:
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        op = MemoryOrigin.OPERATOR.value
        await _add_fact(db, agent, content="older", at=0, dim=facts_table, origin=op)
        await _add_fact(db, agent, content="newer", at=1, dim=facts_table, origin=op)
        # created_at defaults to the transaction clock, so both rows would share it;
        # age one deliberately to pin the order the cap then applies to.
        await db.execute(
            text(
                "UPDATE agent_memory_facts SET created_at = now() - interval '1 hour' "
                "WHERE content = 'older'"
            )
        )
        newest = await memory_repo.list_brief_facts(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            personal_key=None,
            limit=1,
        )
        assert [fact.content for fact in newest] == ["newer"]

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

    async def test_facts_sharing_a_created_at_page_by_id(self, db, facts_table) -> None:
        """Facts written in one transaction share `created_at`, so the newest-first
        sort ties. The id tie-breaker gives the cap and OFFSET/LIMIT a total order,
        so paging visits each fact once instead of dropping or repeating one."""
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        for i in range(3):
            await _add_fact(db, agent, content=f"f{i}", at=i, dim=facts_table)

        rows, total = await memory_repo.list_facts(
            db, organization_id=agent.organization_id, agent_id=agent.id, all_partitions=True
        )
        assert total == 3
        ids = [fact.id for fact in rows]
        # One created_at across all three, so id (asc) breaks the desc tie.
        assert ids == sorted(ids)

        seen = []
        for skip in range(3):
            page, _ = await memory_repo.list_facts(
                db,
                organization_id=agent.organization_id,
                agent_id=agent.id,
                all_partitions=True,
                skip=skip,
                limit=1,
            )
            seen.append(page[0].id)
        assert sorted(seen) == sorted(ids), "each fact once, none dropped or repeated"

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

    async def test_set_fact_origin_promotes_a_fact_into_the_brief(self, db, facts_table) -> None:
        # The whole point of promote: an agent-authored shared fact is recall-only
        # until an operator vouches for it, after which it joins the standing brief.
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        await _add_fact(db, agent, content="learned", at=0, dim=facts_table)
        listed, _ = await memory_repo.list_facts(
            db, organization_id=agent.organization_id, agent_id=agent.id, all_partitions=True
        )
        fact = listed[0]
        assert fact.origin == MemoryOrigin.AGENT.value

        before = await memory_repo.list_brief_facts(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            personal_key=None,
            limit=30,
        )
        assert before == []

        promoted = await memory_repo.set_fact_origin(
            db, fact=fact, origin=MemoryOrigin.OPERATOR.value
        )
        assert promoted.origin == MemoryOrigin.OPERATOR.value

        after = await memory_repo.list_brief_facts(
            db,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            personal_key=None,
            limit=30,
        )
        assert {f.content for f in after} == {"learned"}

    async def test_deleting_the_agent_takes_its_facts(self, db, facts_table) -> None:
        agent = await _agent(db, org=await _org(db, owner=await _user(db)))
        await _add_fact(db, agent, content="x", at=0, dim=facts_table)
        await db.delete(await db.get(Agent, agent.id))
        await db.flush()
        remaining = await db.scalar(
            select(AgentMemoryFact).where(AgentMemoryFact.agent_id == agent.id)
        )
        assert remaining is None
