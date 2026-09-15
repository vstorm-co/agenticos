"""The category/tag discovery filter, against a real Postgres.

Only a real database runs the `&&` overlap operator, builds the GIN indexes and
counts the filtered rows, so the filter's semantics - OR within a facet, AND
across facets, case-insensitive, tenant-safe - are asserted here rather than
against a mock. The write round-trip proves the folded values survive a reload.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import agent as agent_repo
from app.schemas.agent import MAX_TAGS, AgentMetadataRequest, normalize_labels_query
from app.services.agent_registry import AgentRegistryService

pytestmark = pytest.mark.anyio


async def _user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db: AsyncSession) -> tuple[Organization, User]:
    founder = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(org)
    await db.flush()
    return org, founder


async def _agent(
    db: AsyncSession,
    org: Organization,
    owner: User,
    name: str,
    *,
    categories: list[str] | None = None,
    tags: list[str] | None = None,
) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        visibility=Visibility.PRIVATE.value,
        draft_spec=AgentSpec(name=name).model_dump(mode="json"),
        categories=categories or [],
        tags=tags or [],
    )
    db.add(agent)
    await db.flush()
    return agent


async def _visible(
    db: AsyncSession,
    org: Organization,
    owner: User,
    *,
    categories: Sequence[str] = (),
    tags: Sequence[str] = (),
) -> tuple[list[Agent], int]:
    return await agent_repo.list_visible(
        db,
        organization_id=org.id,
        user_id=owner.id,
        see_all=True,
        shared_ids=[],
        categories=list(categories),
        tags=list(tags),
    )


async def test_the_indexes_are_gin(db: AsyncSession) -> None:
    """Codex #4 parity: the model-built schema carries the two GIN indexes."""
    rows = await db.execute(
        text(
            "SELECT c.relname, am.amname FROM pg_class c "
            "JOIN pg_am am ON am.oid = c.relam "
            "WHERE c.relname IN ('ix_agents_categories', 'ix_agents_tags')"
        )
    )
    by_name = dict(rows.all())
    assert by_name == {"ix_agents_categories": "gin", "ix_agents_tags": "gin"}


async def test_a_tag_filter_returns_only_overlapping_rows_and_counts_them(db: AsyncSession) -> None:
    org, owner = await _org(db)
    matched = await _agent(db, org, owner, "Support", tags=["eu", "vip"])
    await _agent(db, org, owner, "Sales", tags=["us"])

    items, total = await _visible(db, org, owner, tags=["eu"])

    assert [a.id for a in items] == [matched.id]
    assert total == 1


async def test_multiple_values_in_one_facet_are_or(db: AsyncSession) -> None:
    org, owner = await _org(db)
    a = await _agent(db, org, owner, "A", tags=["eu"])
    b = await _agent(db, org, owner, "B", tags=["us"])
    await _agent(db, org, owner, "C", tags=["apac"])

    items, total = await _visible(db, org, owner, tags=["eu", "us"])

    assert {x.id for x in items} == {a.id, b.id}
    assert total == 2


async def test_categories_and_tags_are_anded_across_facets(db: AsyncSession) -> None:
    org, owner = await _org(db)
    both = await _agent(db, org, owner, "Both", categories=["support"], tags=["eu"])
    await _agent(db, org, owner, "CatOnly", categories=["support"], tags=["us"])
    await _agent(db, org, owner, "TagOnly", categories=["sales"], tags=["eu"])

    items, total = await _visible(db, org, owner, categories=["support"], tags=["eu"])

    assert [a.id for a in items] == [both.id]
    assert total == 1


async def test_the_match_is_case_insensitive(db: AsyncSession) -> None:
    """Stored values are folded on write, query values on read, so casing agrees."""
    org, owner = await _org(db)
    stored = AgentMetadataRequest(tags=["Sales"]).tags
    matched = await _agent(db, org, owner, "Support", tags=stored)

    queried = normalize_labels_query(["SALES"], max_items=MAX_TAGS)
    items, _total = await _visible(db, org, owner, tags=queried)

    assert [a.id for a in items] == [matched.id]


async def test_a_blank_filter_is_a_no_op(db: AsyncSession) -> None:
    """An empty (normalized) facet applies no predicate, not `&& '{}'`."""
    org, owner = await _org(db)
    await _agent(db, org, owner, "A", tags=["eu"])
    await _agent(db, org, owner, "B", tags=[])

    items, total = await _visible(db, org, owner, tags=normalize_labels_query(["  "], max_items=20))

    assert total == 2
    assert len(items) == 2


async def test_a_filter_never_crosses_a_tenant(db: AsyncSession) -> None:
    org_a, owner_a = await _org(db)
    org_b, owner_b = await _org(db)
    await _agent(db, org_b, owner_b, "Other", tags=["eu"])

    items, total = await _visible(db, org_a, owner_a, tags=["eu"])

    assert items == []
    assert total == 0


async def test_metadata_round_trips_stored_normalized(db: AsyncSession) -> None:
    """Duplicate, empty and mixed-case input persists as the folded, deduped set."""
    org, owner = await _org(db)
    agent = await _agent(db, org, owner, "Support")
    agent_id, org_id = agent.id, org.id
    ctx = AuthContext(user_id=owner.id, organization_id=org_id, role=OrgRoleName.OWNER)
    body = AgentMetadataRequest(categories=["Sales", "sales", "  "], tags=["EU", "eu", "Vip"])

    service = AgentRegistryService(db)
    await service.set_metadata(ctx, agent_id, categories=body.categories, tags=body.tags)

    db.expire_all()
    reloaded = await agent_repo.get(db, agent_id, organization_id=org_id)
    assert reloaded is not None
    assert reloaded.categories == ["sales"]
    assert reloaded.tags == ["eu", "vip"]

    # Clearing a facet stores the empty array rather than leaving the old values.
    await service.set_metadata(ctx, agent_id, categories=[], tags=[])
    db.expire_all()
    cleared = await agent_repo.get(db, agent_id, organization_id=org_id)
    assert cleared is not None
    assert cleared.categories == []
    assert cleared.tags == []
