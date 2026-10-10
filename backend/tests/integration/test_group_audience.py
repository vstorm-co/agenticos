"""A department's resources stay the department's (#2072).

Created for the whole organization by default; limited to named groups in the same
request, which makes them private and shares them with each group.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.group import Group, GroupMember
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.schemas.skill import SkillCreate
from app.services.skills import SkillService

pytestmark = pytest.mark.anyio


async def _person(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _member(db: AsyncSession, organization: Organization, role: str) -> AuthContext:
    person = await _person(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role=role))
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=organization.id, role=role)


async def _department(db: AsyncSession, organization: Organization, *people: AuthContext) -> Group:
    group = Group(organization_id=organization.id, name=f"Dept {uuid.uuid4().hex[:6]}")
    db.add(group)
    await db.flush()
    for person in people:
        assert person.user_id is not None
        db.add(GroupMember(group_id=group.id, user_id=person.user_id))
    await db.flush()
    return group


async def _setup(db: AsyncSession) -> tuple[Organization, AuthContext]:
    owner = await _person(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return organization, AuthContext(
        user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER
    )


async def _create(db: AsyncSession, ctx: AuthContext, data: SkillCreate):
    return await SkillService(db).create(
        ctx,
        name=data.name,
        description=data.description,
        content=data.content,
        visibility=data.visibility,
        group_ids=data.group_ids,
    )


async def _names(db: AsyncSession, ctx: AuthContext) -> list[str]:
    listing = await SkillService(db).list_readable(ctx)
    return [skill.name for skill in listing.items]


async def test_a_skill_is_for_the_whole_organization_unless_limited(db: AsyncSession) -> None:
    organization, owner = await _setup(db)
    anyone = await _member(db, organization, "member")

    await _create(db, owner, SkillCreate(name="house-style", description="How we write."))

    assert "house-style" in await _names(db, anyone)


async def test_a_member_of_sales_does_not_see_a_skill_limited_to_finance(
    db: AsyncSession,
) -> None:
    organization, owner = await _setup(db)
    accountant = await _member(db, organization, "member")
    seller = await _member(db, organization, "member")
    finance = await _department(db, organization, accountant)
    await _department(db, organization, seller)

    skill = await _create(
        db,
        owner,
        SkillCreate(
            name="month-end-close", description="Closing the books.", group_ids=[finance.id]
        ),
    )

    assert skill.visibility == Visibility.PRIVATE.value
    assert "month-end-close" in await _names(db, accountant)
    assert "month-end-close" not in await _names(db, seller)


async def test_a_group_from_another_organization_is_refused_by_name(db: AsyncSession) -> None:
    _, owner = await _setup(db)
    elsewhere, _ = await _setup(db)
    foreign = await _department(db, elsewhere)

    with pytest.raises(BadRequestError) as refused:
        await _create(db, owner, SkillCreate(name="leak", description="x", group_ids=[foreign.id]))

    assert refused.value.details["fields"][0]["field"] == "group_ids"


async def test_a_department_page_lists_what_it_was_given_that_the_reader_may_see(
    db: AsyncSession,
) -> None:
    from app.db.models.resource_grant import GrantLevel, ResourceGrant
    from app.services.group import GroupService

    organization, owner = await _setup(db)
    accountant = await _member(db, organization, "member")
    finance = await _department(db, organization, accountant)
    await _create(
        db,
        owner,
        SkillCreate(name="month-end-close", description="Closing.", group_ids=[finance.id]),
    )
    # A grant left behind by a skill that no longer exists names nothing to show.
    db.add(
        ResourceGrant(
            organization_id=organization.id,
            subject_group_id=finance.id,
            resource_type="skill",
            resource_id=uuid.uuid4(),
            level=GrantLevel.READ.value,
        )
    )
    await db.flush()

    listed = await GroupService(db).resources(accountant, finance.id)

    assert [(item.kind, item.name, item.level) for item in listed] == [
        ("skill", "month-end-close", "use")
    ]


async def test_a_group_keeps_its_icon_and_can_lose_it(db: AsyncSession) -> None:
    from app.schemas.group import GroupCreate, GroupUpdate
    from app.services.group import GroupService

    organization, owner = await _setup(db)
    assert owner.user_id is not None
    service = GroupService(db)

    group = await service.create(
        organization.id, owner.user_id, GroupCreate(name="Finance", icon="banknote")
    )
    assert group.icon == "banknote"

    updated, _ = await service.update(
        organization.id, group.id, owner.user_id, GroupUpdate(icon=None)
    )
    assert updated.icon is None


class TestKnowledgeReach:
    """An agent shared wider than its knowledge answers everyone from it (#2072)."""

    async def _agent(self, db: AsyncSession, owner: AuthContext, **spec_fields: object):
        from app.agents.spec import AgentSpec
        from app.services.agent_registry import AgentRegistryService

        spec = AgentSpec.model_validate({"name": f"A {uuid.uuid4().hex[:6]}", **spec_fields})
        return await AgentRegistryService(db).create(ctx=owner, spec=spec)

    async def test_an_organization_agent_reading_a_finance_skill_is_flagged(
        self, db: AsyncSession
    ) -> None:
        from app.services.knowledge_reach import KnowledgeReachService

        organization, owner = await _setup(db)
        finance = await _department(db, organization)
        skill = await _create(
            db, owner, SkillCreate(name="ledger", description="x", group_ids=[finance.id])
        )
        open_skill = await _create(db, owner, SkillCreate(name="style", description="x"))
        agent = await self._agent(db, owner, skill_ids=[skill.id, open_skill.id])
        agent.visibility = Visibility.ORG.value
        await db.flush()

        reach = await KnowledgeReachService(db).for_agent(owner, agent.id)

        assert reach.whole_organization
        by_name = {source.name: source for source in reach.sources}
        assert by_name["ledger"].groups == [finance.name]
        assert by_name["ledger"].reaches_fewer_than_agent
        assert by_name["style"].whole_organization
        assert not by_name["style"].reaches_fewer_than_agent

    async def test_a_finance_agent_reading_finance_knowledge_is_not_flagged(
        self, db: AsyncSession
    ) -> None:
        from app.services.knowledge_reach import KnowledgeReachService

        organization, owner = await _setup(db)
        finance = await _department(db, organization)
        sales = await _department(db, organization)
        skill = await _create(
            db, owner, SkillCreate(name="ledger", description="x", group_ids=[finance.id])
        )
        mixed = await _create(
            db, owner, SkillCreate(name="pipeline", description="x", group_ids=[sales.id])
        )
        agent = await self._agent(db, owner, skill_ids=[skill.id, mixed.id])
        from app.services.access import AGENT
        from app.services.agent_registry import AgentRegistryService
        from app.services.sharing import SharingService

        agent.visibility = Visibility.PRIVATE.value
        await db.flush()
        await SharingService(db).restrict_to_groups(
            owner, agent, resource_type=AGENT, group_ids=[finance.id]
        )
        assert await AgentRegistryService(db).get(owner, agent.id)

        reach = await KnowledgeReachService(db).for_agent(owner, agent.id)

        assert reach.groups == [finance.name]
        by_name = {source.name: source for source in reach.sources}
        assert not by_name["ledger"].reaches_fewer_than_agent
        assert by_name["pipeline"].reaches_fewer_than_agent


async def test_a_department_page_names_its_agents_context_and_apps(db: AsyncSession) -> None:
    """Each kind created for a group, or shared with it, is on the group's page."""
    from app.agents.spec import AgentSpec
    from app.db.models.artifact import Artifact
    from app.db.models.resource_grant import GrantLevel, ResourceGrant
    from app.services.agent_registry import AgentRegistryService
    from app.services.context import ContextService
    from app.services.group import GroupService

    organization, owner = await _setup(db)
    finance = await _department(db, organization)
    await AgentRegistryService(db).create(
        owner, AgentSpec(name="Payables"), visibility=Visibility.PRIVATE, group_ids=[finance.id]
    )
    await ContextService(db).create(
        owner,
        name="chart-of-accounts",
        description=None,
        content="1000 Cash",
        visibility=Visibility.PRIVATE,
        group_ids=[finance.id],
    )
    app = Artifact(
        organization_id=organization.id,
        owner_user_id=owner.user_id,
        visibility=Visibility.PRIVATE.value,
        name="close-checklist",
        title="Close checklist",
    )
    db.add(app)
    await db.flush()
    db.add(
        ResourceGrant(
            organization_id=organization.id,
            subject_group_id=finance.id,
            resource_type="artifact",
            resource_id=app.id,
            level=GrantLevel.READ.value,
        )
    )
    await db.flush()

    listed = await GroupService(db).resources(owner, finance.id)

    assert sorted((item.kind, item.name) for item in listed) == [
        ("agent", "Payables"),
        ("artifact", "Close checklist"),
        ("context", "chart-of-accounts"),
    ]


async def test_a_source_the_reader_cannot_see_is_left_out_of_the_agent_s_reach(
    db: AsyncSession,
) -> None:
    from app.agents.spec import AgentSpec
    from app.services.agent_registry import AgentRegistryService
    from app.services.knowledge_reach import KnowledgeReachService

    organization, owner = await _setup(db)
    reader = await _member(db, organization, "member")
    hidden = await _create(
        db, owner, SkillCreate(name="board-notes", description="x", visibility=Visibility.PRIVATE)
    )
    agent = await AgentRegistryService(db).create(
        owner, AgentSpec(name="Everyone's", skill_ids=[hidden.id]), visibility=Visibility.ORG
    )

    reach = await KnowledgeReachService(db).for_agent(reader, agent.id)

    assert reach.sources == []
