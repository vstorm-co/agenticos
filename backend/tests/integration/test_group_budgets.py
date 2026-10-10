"""A department's monthly budget: what it meters, who hears, and what it exports (#2072)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetScope
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.group import Group, GroupMember
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import agent_run_repo, group_repo
from app.schemas.group import GroupCreate, GroupUpdate
from app.services.group import GroupService
from app.services.group_spend import GroupSpendService
from app.services.notifications import NotificationService
from app.services.spend import month_start

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _person(db: AsyncSession, email: str | None = None) -> User:
    user = User(
        email=email or f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(user)
    await db.flush()
    return user


class _Org:
    """An organization with an owner, an agent, and a way to add people and runs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build(self) -> _Org:
        self.owner = await _person(self.db)
        self.organization = Organization(
            name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=self.owner.id
        )
        self.db.add(self.organization)
        await self.db.flush()
        self.db.add(
            OrganizationMember(
                organization_id=self.organization.id, user_id=self.owner.id, role="owner"
            )
        )
        self.agent = Agent(
            organization_id=self.organization.id,
            owner_user_id=self.owner.id,
            name="Payables",
            slug=f"payables-{uuid.uuid4().hex[:8]}",
            draft_spec=AgentSpec(name="Payables").model_dump(mode="json"),
            visibility=Visibility.ORG.value,
        )
        self.db.add(self.agent)
        await self.db.flush()
        return self

    @property
    def owner_ctx(self) -> AuthContext:
        return AuthContext(
            user_id=self.owner.id, organization_id=self.organization.id, role=OrgRoleName.OWNER
        )

    async def member(self, email: str | None = None) -> AuthContext:
        person = await _person(self.db, email)
        self.db.add(
            OrganizationMember(
                organization_id=self.organization.id, user_id=person.id, role="member"
            )
        )
        await self.db.flush()
        return AuthContext(user_id=person.id, organization_id=self.organization.id, role="member")

    async def department(
        self, name: str, cap: str | None, *people: AuthContext, lead: AuthContext | None = None
    ) -> Group:
        group = Group(
            organization_id=self.organization.id,
            name=name,
            monthly_budget_usd=Decimal(cap) if cap else None,
        )
        self.db.add(group)
        await self.db.flush()
        for person in people:
            assert person.user_id is not None
            self.db.add(
                GroupMember(group_id=group.id, user_id=person.user_id, is_lead=person is lead)
            )
        await self.db.flush()
        return group

    async def run(
        self, who: AuthContext | None, cost: str, *, last_month: bool = False
    ) -> AgentRun:
        started = month_start() - timedelta(days=3) if last_month else datetime.now(UTC)
        run = AgentRun(
            organization_id=self.organization.id,
            agent_id=self.agent.id,
            user_id=who.user_id if who else None,
            status="completed",
            surface="web",
            cost_usd=Decimal(cost),
            started_at=started,
        )
        self.db.add(run)
        await self.db.flush()
        return run


async def _notices(db: AsyncSession, event: NotificationEventType) -> list[tuple[uuid.UUID, str]]:
    rows = await db.execute(
        select(Notification.recipient_user_id, Notification.summary).where(
            Notification.event_type == event.value
        )
    )
    return [(recipient, summary) for recipient, summary in rows.all()]


class TestWhatADepartmentMeters:
    async def test_its_month_is_what_its_members_ran_this_month(self, db: AsyncSession) -> None:
        org = await _Org(db).build()
        anna, bob, outsider = await org.member(), await org.member(), await org.member()
        finance = await org.department("Finance", "10", anna, bob)
        await org.run(anna, "2.50")
        await org.run(bob, "1.00")
        await org.run(outsider, "9.00")
        await org.run(anna, "5.00", last_month=True)

        spent = await agent_run_repo.sum_cost_since(
            db, organization_id=org.organization.id, since=month_start(), group_id=finance.id
        )

        assert spent == Decimal("3.50")

    async def test_only_capped_departments_bind_and_each_has_its_leads(
        self, db: AsyncSession
    ) -> None:
        org = await _Org(db).build()
        anna, lead = await org.member(), await org.member()
        finance = await org.department("Finance", "10", anna, lead, lead=lead)
        await org.department("Book club", None, anna)
        other = await _Org(db).build()
        await other.department("Elsewhere", "5", anna)
        assert anna.user_id is not None

        capped = await group_repo.capped_groups_for_member(
            db, organization_id=org.organization.id, user_id=anna.user_id
        )

        assert [(group.id, group.monthly_budget_usd) for group in capped] == [
            (finance.id, Decimal("10.000000"))
        ]
        assert await group_repo.lead_ids(db, [finance.id]) == [lead.user_id]


class TestWhoHears:
    async def test_a_department_that_crosses_80_percent_warns_its_lead_once(
        self, db: AsyncSession
    ) -> None:
        org = await _Org(db).build()
        anna, lead = await org.member(), await org.member()
        await org.department("Finance", "10", anna, lead, lead=lead)
        notifier = NotificationService(db)

        await notifier.department_budget_warnings(await org.run(anna, "7.00"))
        assert await _notices(db, NotificationEventType.BUDGET_WARNING) == []

        await notifier.department_budget_warnings(await org.run(anna, "1.50"))
        await notifier.department_budget_warnings(await org.run(anna, "0.10"))

        warned = await _notices(db, NotificationEventType.BUDGET_WARNING)
        assert sorted(recipient for recipient, _ in warned) == sorted([org.owner.id, lead.user_id])
        assert {summary for _, summary in warned} == {
            "Finance has used 85% of its $10.00 monthly budget."
        }

    async def test_a_run_nobody_started_warns_nobody(self, db: AsyncSession) -> None:
        org = await _Org(db).build()
        await NotificationService(db).department_budget_warnings(await org.run(None, "50"))

        assert await _notices(db, NotificationEventType.BUDGET_WARNING) == []

    async def test_a_department_cap_stopping_a_run_tells_its_lead_and_the_admins(
        self, db: AsyncSession
    ) -> None:
        org = await _Org(db).build()
        anna, lead = await org.member(), await org.member()
        await org.department("Finance", "1", anna, lead, lead=lead)
        run = await org.run(anna, "1.20")

        await NotificationService(db).budget_exceeded(
            run,
            agent=org.agent,
            spec=AgentSpec(name="Payables"),
            reason="Finance department monthly budget exhausted",
            scope=BudgetScope.GROUP,
        )

        told = {
            recipient for recipient, _ in await _notices(db, NotificationEventType.BUDGET_EXCEEDED)
        }
        assert told == {org.owner.id, lead.user_id}
        assert anna.user_id not in told


class TestTheSpendPage:
    async def test_every_department_with_its_month_costliest_first(self, db: AsyncSession) -> None:
        org = await _Org(db).build()
        anna, bob = await org.member(), await org.member()
        finance = await org.department("Finance", "10", anna, bob)
        sales = await org.department("Sales", None, bob)
        idle = await org.department("Legal", "5")
        await org.run(anna, "3")
        await org.run(bob, "1")

        month = await GroupSpendService(db).month(org.owner_ctx)

        assert month.since == month_start()
        assert [(item.group_id, item.spent_usd, item.run_count) for item in month.items] == [
            (finance.id, Decimal("4"), 2),
            (sales.id, Decimal("1"), 1),
            (idle.id, Decimal("0"), 0),
        ]

    async def test_the_export_is_a_row_per_member_and_agent(self, db: AsyncSession) -> None:
        org = await _Org(db).build()
        anna = await org.member("anna@acme.example")
        lead = await org.member("lead@acme.example")
        finance = await org.department("Finance", "10", anna, lead, lead=lead)
        await org.run(anna, "2")
        await org.run(anna, "1")
        await org.run(lead, "0.5")

        export = await GroupSpendService(db).export(lead, finance.id)

        assert export.content.splitlines() == [
            "member,agent,runs,cost_usd",
            "anna@acme.example,Payables,2,3.000000",
            "lead@acme.example,Payables,1,0.500000",
        ]
        assert export.filename.startswith("Finance-spend-")
        assert export.row_count == 2

    async def test_a_member_who_neither_sees_spend_nor_leads_is_refused(
        self, db: AsyncSession
    ) -> None:
        org = await _Org(db).build()
        anna = await org.member()
        finance = await org.department("Finance", "10", anna)
        service = GroupSpendService(db)

        with pytest.raises(AuthorizationError):
            await service.export(anna, finance.id)
        keyless = AuthContext(user_id=None, organization_id=org.organization.id, role="member")
        with pytest.raises(AuthorizationError):
            await service.export(keyless, finance.id)
        with pytest.raises(NotFoundError):
            await service.export(org.owner_ctx, uuid.uuid4())


class TestSettingTheCap:
    async def test_a_cap_is_set_kept_and_removed(self, db: AsyncSession) -> None:
        org = await _Org(db).build()
        service = GroupService(db)
        owner = org.owner.id

        group = await service.create(
            org.organization.id,
            owner,
            GroupCreate(name="Finance", monthly_budget_usd=Decimal("50")),
        )
        assert group.monthly_budget_usd == Decimal("50")

        renamed, _count = await service.update(
            org.organization.id, group.id, owner, GroupUpdate(name="Finance & Ops")
        )
        assert renamed.monthly_budget_usd == Decimal("50")

        uncapped, _count = await service.update(
            org.organization.id, group.id, owner, GroupUpdate(monthly_budget_usd=None)
        )
        assert uncapped.monthly_budget_usd is None
