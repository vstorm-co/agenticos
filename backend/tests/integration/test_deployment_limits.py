"""The two ceilings a deployment can set, and what they refuse.

Both are null by default, and null is *no limit* rather than "not configured" -
an installation that has never opened the settings page is uncapped, which is
what a self-hosted deployment for one company wants.

The refusals are the whole feature, so they are what is asserted: an account at
its ceiling cannot mint another tenant, an organization at its ceiling cannot
add another agent, and neither refusal is a surprise - each names the limit and
the count it was measured against.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import AgentStatus
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import member_repo
from app.schemas.organization import OrganizationCreate
from app.services.agent_registry import AgentRegistryService
from app.services.member import MemberService
from app.services.organization import OrganizationService

pytestmark = pytest.mark.anyio


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


async def _org(db, owner: User, *, personal: bool = False) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
        is_personal=personal,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=org.id,
            user_id=owner.id,
            role=OrgRoleName.OWNER.value,
        )
    )
    await db.flush()
    return org


async def _limits(db, **columns) -> None:
    db.add(DeploymentSettings(id=uuid.uuid4(), singleton=True, **columns))
    await db.flush()


def _ctx(org: Organization, user: User) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


class TestOrganizationsPerAccount:
    async def test_an_uncapped_deployment_refuses_nothing(self, db) -> None:
        owner = await _user(db)
        await _org(db, owner, personal=True)

        created = await OrganizationService(db).create(OrganizationCreate(name="Second"), owner.id)

        assert created.id is not None

    async def test_an_account_at_its_ceiling_is_refused(self, db) -> None:
        # The personal organization counts, because it is one - which is why the
        # schema refuses a ceiling of zero.
        owner = await _user(db)
        await _org(db, owner, personal=True)
        await _limits(db, max_organizations_per_user=1)

        with pytest.raises(BadRequestError) as refusal:
            await OrganizationService(db).create(OrganizationCreate(name="Second"), owner.id)

        # Named, so the answer to "why can I not" is in the response rather than
        # in an administrator's memory.
        assert refusal.value.details == {"limit": 1, "owned": 1}

    async def test_being_invited_into_organizations_does_not_spend_the_ceiling(self, db) -> None:
        """Owned rather than joined: a ceiling one person cannot control is a
        ceiling that locks them out of creating their own."""
        owner = await _user(db)
        await _org(db, owner, personal=True)
        somebody_else = await _user(db)
        theirs = await _org(db, somebody_else)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=theirs.id,
                user_id=owner.id,
                role=OrgRoleName.MEMBER.value,
            )
        )
        await db.flush()
        await _limits(db, max_organizations_per_user=2)

        created = await OrganizationService(db).create(OrganizationCreate(name="Second"), owner.id)

        assert created.id is not None


class TestAgentsPerOrganization:
    async def test_an_organization_at_its_ceiling_is_refused(self, db) -> None:
        owner = await _user(db)
        org = await _org(db, owner)
        await _limits(db, max_agents_per_organization=1)
        registry = AgentRegistryService(db)
        await registry.create(_ctx(org, owner), AgentSpec(name="First"))

        with pytest.raises(BadRequestError) as refusal:
            await registry.create(_ctx(org, owner), AgentSpec(name="Second"))

        assert refusal.value.details == {"limit": 1, "held": 1}

    async def test_archiving_an_agent_frees_its_place(self, db) -> None:
        """Archiving is how an agent is retired. A ceiling a retired agent went
        on occupying would make the only way back under it a delete - which
        takes the version history and the run attribution with it."""
        owner = await _user(db)
        org = await _org(db, owner)
        await _limits(db, max_agents_per_organization=1)
        registry = AgentRegistryService(db)
        first = await registry.create(_ctx(org, owner), AgentSpec(name="First"))
        first.status = AgentStatus.ARCHIVED.value
        await db.flush()

        created = await registry.create(_ctx(org, owner), AgentSpec(name="Second"))

        assert created.id is not None

    async def test_another_organization_ceiling_is_its_own(self, db) -> None:
        owner = await _user(db)
        mine, theirs = await _org(db, owner), await _org(db, owner)
        await _limits(db, max_agents_per_organization=1)
        registry = AgentRegistryService(db)
        await registry.create(_ctx(mine, owner), AgentSpec(name="First"))

        created = await registry.create(_ctx(theirs, owner), AgentSpec(name="First"))

        assert created.organization_id == theirs.id

    async def test_restoring_an_archived_agent_is_refused_at_the_ceiling(self, db) -> None:
        """The way past the ceiling if only creates are checked: archive one, create
        a replacement, restore what you archived. The count is of live agents, so a
        restore is a transition *into* the counted state."""
        owner = await _user(db)
        org = await _org(db, owner)
        await _limits(db, max_agents_per_organization=1)
        registry = AgentRegistryService(db)
        first = await registry.create(_ctx(org, owner), AgentSpec(name="First"))
        await registry.archive(_ctx(org, owner), first.id)
        await registry.create(_ctx(org, owner), AgentSpec(name="Second"))

        with pytest.raises(BadRequestError) as refusal:
            await registry.unarchive(_ctx(org, owner), first.id)

        assert refusal.value.details == {"limit": 1, "held": 1}

    async def test_restoring_below_the_ceiling_still_works(self, db) -> None:
        owner = await _user(db)
        org = await _org(db, owner)
        await _limits(db, max_agents_per_organization=2)
        registry = AgentRegistryService(db)
        first = await registry.create(_ctx(org, owner), AgentSpec(name="First"))
        await registry.archive(_ctx(org, owner), first.id)

        restored = await registry.unarchive(_ctx(org, owner), first.id)

        assert restored.status != AgentStatus.ARCHIVED.value


class TestATransitionIntoOwnership:
    """A ceiling on new rows alone is one an account walks past sideways.

    `MemberService.transfer_ownership` makes an existing member an owner, which is
    the same transition `OrganizationService.create` performs and the same count it
    spends - so it asks the same question.
    """

    async def test_an_account_at_its_ceiling_cannot_be_handed_another_organization(
        self, db
    ) -> None:
        owner, colleague = await _user(db), await _user(db)
        await _org(db, colleague, personal=True)
        org = await _org(db, owner)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=colleague.id,
                role=OrgRoleName.ADMIN.value,
            )
        )
        await db.flush()
        await _limits(db, max_organizations_per_user=1)

        with pytest.raises(BadRequestError) as refusal:
            await MemberService(db).transfer_ownership(org.id, colleague.id, owner.id)

        assert refusal.value.details == {"limit": 1, "owned": 1}

    async def test_a_transfer_below_the_ceiling_still_works(self, db) -> None:
        owner, colleague = await _user(db), await _user(db)
        await _org(db, colleague, personal=True)
        org = await _org(db, owner)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=colleague.id,
                role=OrgRoleName.ADMIN.value,
            )
        )
        await db.flush()
        await _limits(db, max_organizations_per_user=3)

        await MemberService(db).transfer_ownership(org.id, colleague.id, owner.id)

        rows = await member_repo.get(db, organization_id=org.id, user_id=colleague.id)
        assert rows is not None and rows.role == OrgRoleName.OWNER.value


class TestTwoRequestsRacingOnTheLastPlace:
    """The ceiling is a count read and then acted on, which is two statements.

    Under the default isolation both requests pass the count and both write, so a
    deployment allowing one agent ends up with two - deterministically, by clicking
    twice. No constraint can express "at most N rows like this", so the subject of
    the ceiling is locked for the length of the transaction instead. Two sessions
    are the only way to see that work.
    """

    async def test_only_one_of_two_concurrent_creates_gets_the_last_place(self, db, engine) -> None:
        owner = await _user(db)
        org = await _org(db, owner)
        await _limits(db, max_agents_per_organization=1)
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def create(name: str) -> bool:
            async with factory() as session:
                try:
                    await AgentRegistryService(session).create(
                        _ctx(org, owner), AgentSpec(name=name)
                    )
                    await session.commit()
                except BadRequestError:
                    await session.rollback()
                    return False
                return True

        both = await asyncio.gather(create("First"), create("Second"))

        assert both.count(True) == 1

    async def test_only_one_of_two_concurrent_organizations_is_created(self, db, engine) -> None:
        owner = await _user(db)
        await _org(db, owner, personal=True)
        await _limits(db, max_organizations_per_user=2)
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def create(name: str) -> bool:
            async with factory() as session:
                try:
                    await OrganizationService(session).create(
                        OrganizationCreate(name=name), owner.id
                    )
                    await session.commit()
                except BadRequestError:
                    await session.rollback()
                    return False
                return True

        both = await asyncio.gather(create("Second"), create("Third"))

        assert both.count(True) == 1
