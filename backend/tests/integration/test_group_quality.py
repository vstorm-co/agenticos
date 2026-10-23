"""How well agents answer a department's people, against a real database (#2101)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.group import Group, GroupMember
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.services.group_quality import GroupQualityService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


class _Org:
    """An organization, its agents, its departments, and answers its people rated."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build(self) -> _Org:
        self.owner = await self._person()
        self.organization = Organization(
            name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=self.owner
        )
        self.db.add(self.organization)
        await self.db.flush()
        self.db.add(
            OrganizationMember(
                organization_id=self.organization.id, user_id=self.owner, role="owner"
            )
        )
        await self.db.flush()
        return self

    async def _person(self) -> uuid.UUID:
        user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
        self.db.add(user)
        await self.db.flush()
        return user.id

    @property
    def owner_ctx(self) -> AuthContext:
        return AuthContext(
            user_id=self.owner, organization_id=self.organization.id, role=OrgRoleName.OWNER
        )

    async def member(self) -> AuthContext:
        person = await self._person()
        self.db.add(
            OrganizationMember(organization_id=self.organization.id, user_id=person, role="member")
        )
        await self.db.flush()
        return AuthContext(user_id=person, organization_id=self.organization.id, role="member")

    async def agent(self, name: str) -> Agent:
        agent = Agent(
            organization_id=self.organization.id,
            owner_user_id=self.owner,
            name=name,
            slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
            draft_spec=AgentSpec(name=name).model_dump(mode="json"),
            visibility=Visibility.ORG.value,
        )
        self.db.add(agent)
        await self.db.flush()
        return agent

    async def department(
        self, name: str, *people: AuthContext, lead: AuthContext | None = None
    ) -> Group:
        group = Group(organization_id=self.organization.id, name=name)
        self.db.add(group)
        await self.db.flush()
        for person in people:
            assert person.user_id is not None
            self.db.add(
                GroupMember(group_id=group.id, user_id=person.user_id, is_lead=person is lead)
            )
        await self.db.flush()
        return group

    async def answer(
        self, who: AuthContext, agent: Agent, rating: int, comment: str | None = None
    ) -> AgentRun:
        """A run `who` started, its answer, and `who`'s thumb on it."""
        run = AgentRun(
            organization_id=self.organization.id,
            agent_id=agent.id,
            user_id=who.user_id,
            status="completed",
            surface="web",
            started_at=datetime.now(UTC),
        )
        conversation = Conversation(organization_id=self.organization.id, user_id=who.user_id)
        self.db.add_all([run, conversation])
        await self.db.flush()
        message = Message(
            conversation_id=conversation.id, role="assistant", content="answered", run_id=run.id
        )
        self.db.add(message)
        await self.db.flush()
        assert who.user_id is not None
        self.db.add(
            MessageRating(
                message_id=message.id, user_id=who.user_id, rating=rating, comment=comment
            )
        )
        await self.db.flush()
        return run


async def test_a_lead_sees_the_split_the_busiest_agents_and_the_worst_answers(
    db: AsyncSession,
) -> None:
    org = await _Org(db).build()
    anna, lead, outsider = await org.member(), await org.member(), await org.member()
    finance = await org.department("Finance", anna, lead, lead=lead)
    payables, ledger = await org.agent("Payables"), await org.agent("Ledger")
    await org.answer(anna, payables, 1)
    await org.answer(anna, payables, 1)
    wrong = await org.answer(lead, ledger, -1, "Wrong VAT rate")
    await org.answer(outsider, ledger, -1, "Not Finance's problem")
    # A widget visitor the lead stands in for as publisher: not the department's
    # own activity, so not in its ranking (Codex on #2062).
    for _ in range(3):
        db.add(
            AgentRun(
                organization_id=org.organization.id,
                agent_id=ledger.id,
                user_id=lead.user_id,
                status="completed",
                surface="embed",
                started_at=datetime.now(UTC),
                initiated_by_publisher_fallback=True,
            )
        )
    await db.flush()

    quality = await GroupQualityService(db).detail(lead, finance.id, from_date=None, to_date=None)

    assert (quality.likes, quality.dislikes) == (2, 1)
    assert [(use.name, use.run_count) for use in quality.top_agents] == [
        ("Payables", 2),
        ("Ledger", 1),
    ]
    ((answer,),) = [quality.down_rated]
    assert (answer.comment, answer.run_id, answer.agent_name) == (
        "Wrong VAT rate",
        wrong.id,
        "Ledger",
    )


async def test_the_overview_ranks_departments_least_helpful_first(db: AsyncSession) -> None:
    org = await _Org(db).build()
    anna, bob = await org.member(), await org.member()
    finance = await org.department("Finance", anna)
    sales = await org.department("Sales", bob)
    await org.department("Quiet")
    agent = await org.agent("Helper")
    await org.answer(anna, agent, 1)
    await org.answer(bob, agent, -1)
    await org.answer(bob, agent, 1)

    overview = await GroupQualityService(db).overview(org.owner_ctx, from_date=None, to_date=None)

    assert [(item.group_id, item.likes, item.dislikes) for item in overview.items] == [
        (sales.id, 1, 1),
        (finance.id, 1, 0),
    ]


async def test_a_member_of_another_department_sees_none_of_it(db: AsyncSession) -> None:
    org = await _Org(db).build()
    anna, bob = await org.member(), await org.member()
    finance = await org.department("Finance", anna)
    await org.department("Sales", bob, lead=bob)
    service = GroupQualityService(db)

    # A lead of Sales, an ordinary member of Finance, nobody at all.
    with pytest.raises(AuthorizationError):
        await service.detail(bob, finance.id, from_date=None, to_date=None)
    with pytest.raises(AuthorizationError):
        await service.detail(anna, finance.id, from_date=None, to_date=None)
    keyless = AuthContext(user_id=None, organization_id=org.organization.id, role="member")
    with pytest.raises(AuthorizationError):
        await service.detail(keyless, finance.id, from_date=None, to_date=None)
    with pytest.raises(NotFoundError):
        await service.detail(org.owner_ctx, uuid.uuid4(), from_date=None, to_date=None)


async def test_a_department_nobody_rated_reads_as_empty_not_missing(db: AsyncSession) -> None:
    org = await _Org(db).build()
    finance = await org.department("Finance", await org.member())

    quality = await GroupQualityService(db).detail(
        org.owner_ctx, finance.id, from_date=None, to_date=None
    )

    assert (quality.likes, quality.dislikes, quality.top_agents, quality.down_rated) == (
        0,
        0,
        [],
        [],
    )
