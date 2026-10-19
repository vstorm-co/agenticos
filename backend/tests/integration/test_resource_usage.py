"""Which agents use a skill, a context file or a knowledge base (#2075)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentStatus
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.services.resource_usage import agents_using

pytestmark = pytest.mark.anyio


async def _person(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _organization(db: AsyncSession) -> tuple[Organization, AuthContext]:
    owner = await _person(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return organization, AuthContext(
        user_id=owner.id, organization_id=organization.id, role="owner"
    )


async def _agent(
    db: AsyncSession,
    ctx: AuthContext,
    name: str,
    *,
    skill_ids: list[uuid.UUID] | None = None,
    visibility: Visibility = Visibility.ORG,
    status: AgentStatus = AgentStatus.DRAFT,
) -> Agent:
    spec = AgentSpec(name=name, skill_ids=skill_ids or []).model_dump(mode="json")
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        visibility=visibility.value,
        status=status.value,
        draft_spec=spec,
    )
    db.add(agent)
    await db.flush()
    return agent


async def test_each_resource_names_the_agents_binding_it_in_name_order(db: AsyncSession) -> None:
    _, owner = await _organization(db)
    refunds, unused = uuid.uuid4(), uuid.uuid4()
    await _agent(db, owner, "Support", skill_ids=[refunds])
    await _agent(db, owner, "Billing", skill_ids=[refunds])
    await _agent(db, owner, "Sales")

    used = await agents_using(db, owner, field="skill_ids", resource_ids=[refunds, unused])

    assert [agent.name for agent in used[refunds]] == ["Billing", "Support"]
    assert used[unused] == []


async def test_an_archived_agent_uses_nothing(db: AsyncSession) -> None:
    _, owner = await _organization(db)
    refunds = uuid.uuid4()
    await _agent(db, owner, "Retired", skill_ids=[refunds], status=AgentStatus.ARCHIVED)

    used = await agents_using(db, owner, field="skill_ids", resource_ids=[refunds])

    assert used[refunds] == []


async def test_another_organizations_agent_is_never_named(db: AsyncSession) -> None:
    _, mine = await _organization(db)
    _, theirs = await _organization(db)
    shared_id = uuid.uuid4()
    await _agent(db, theirs, "Theirs", skill_ids=[shared_id])

    used = await agents_using(db, mine, field="skill_ids", resource_ids=[shared_id])

    assert used[shared_id] == []


async def test_a_private_agent_is_not_named_to_somebody_who_cannot_see_it(
    db: AsyncSession,
) -> None:
    organization, owner = await _organization(db)
    member = await _person(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=member.id, role="member"))
    await db.flush()
    as_member = AuthContext(user_id=member.id, organization_id=organization.id, role="member")
    refunds = uuid.uuid4()
    await _agent(db, owner, "Private", skill_ids=[refunds], visibility=Visibility.PRIVATE)
    await _agent(db, owner, "Shared", skill_ids=[refunds])

    used = await agents_using(db, as_member, field="skill_ids", resource_ids=[refunds])

    assert [agent.name for agent in used[refunds]] == ["Shared"]


async def test_nothing_asked_is_nothing_queried(db: AsyncSession) -> None:
    _, owner = await _organization(db)

    assert await agents_using(db, owner, field="context_ids", resource_ids=[]) == {}
