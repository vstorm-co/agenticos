"""Who may watch a browse, and who may drive it (#2128), against a real database.

Watching takes being the person the run acts for, editing the agent, or viewing
runs. Driving takes one of the first two, because what is done in the browser is
done as the agent - so an operator who watches every run still cannot type into
one. Each answer is a join between a token, a membership and the agent's grants.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import OrgRoleName
from app.core.security import create_access_token
from app.db.models.agent import Agent
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.services import live_browse
from app.services.live_browse import BrowseMeta

pytestmark = pytest.mark.anyio


async def _person(db: AsyncSession, name: str | None = None) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True, full_name=name
    )
    db.add(user)
    await db.flush()
    return user


async def _organization(db: AsyncSession, owner: User) -> Organization:
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return organization


async def _join(db: AsyncSession, organization: Organization, role: str) -> User:
    person = await _person(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role=role))
    await db.flush()
    return person


async def _agent(db: AsyncSession, organization: Organization, owner: User) -> Agent:
    agent = Agent(
        organization_id=organization.id,
        owner_user_id=owner.id,
        name="Purchasing",
        slug=f"purchasing-{uuid.uuid4().hex[:8]}",
        visibility=Visibility.ORG,
        draft_spec={"name": "Purchasing", "instructions": "Order supplies."},
    )
    db.add(agent)
    await db.flush()
    return agent


def _meta(organization: Organization, agent: Agent | None, acting_for: User | None) -> BrowseMeta:
    return BrowseMeta(
        organization_id=organization.id,
        agent_id=None if agent is None else agent.id,
        user_id=None if acting_for is None else str(acting_for.id),
        task="Sign in to the supplier portal",
        started_at=datetime.now(UTC),
    )


def _token(user: User) -> str:
    return create_access_token(str(user.id))


class TestWhoMayDrive:
    async def test_the_person_the_run_acts_for_may_drive_it(self, db: AsyncSession) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        agent = await _agent(db, organization, owner)
        member = await _join(db, organization, OrgRoleName.MEMBER)
        await db.commit()

        access = await live_browse.access_for(_meta(organization, agent, member), _token(member))

        assert access is not None
        assert access.control and access.own
        assert access.user_id == str(member.id)
        # Nobody named them: the address they signed in with is who they are.
        assert access.name == member.email

    async def test_someone_who_may_edit_the_agent_may_drive_another_s_run(
        self, db: AsyncSession
    ) -> None:
        owner = await _person(db, "Ada Lovelace")
        organization = await _organization(db, owner)
        agent = await _agent(db, organization, owner)
        member = await _join(db, organization, OrgRoleName.MEMBER)
        await db.commit()

        access = await live_browse.access_for(_meta(organization, agent, member), _token(owner))

        assert access is not None
        assert access.control and not access.own
        assert access.name == "Ada Lovelace"


class TestWhoMayOnlyWatch:
    @pytest.mark.security
    async def test_viewing_runs_is_watching_not_driving(self, db: AsyncSession) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        agent = await _agent(db, organization, owner)
        operator = await _join(db, organization, OrgRoleName.OPERATOR)
        await db.commit()

        access = await live_browse.access_for(_meta(organization, agent, owner), _token(operator))

        assert access is not None
        assert not access.control

    async def test_a_browse_with_no_agent_and_nobody_behind_it_is_watched_by_run_viewers(
        self, db: AsyncSession
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        operator = await _join(db, organization, OrgRoleName.OPERATOR)
        await db.commit()

        access = await live_browse.access_for(_meta(organization, None, None), _token(operator))

        assert access is not None
        assert not access.control


class TestWhoMayNotWatch:
    @pytest.mark.security
    async def test_a_sign_in_from_settings_is_seen_by_its_person_alone(
        self, db: AsyncSession
    ) -> None:
        """Its pictures are somebody typing a password. Viewing runs, or owning
        the organization, is not a reason to watch."""
        owner = await _person(db)
        organization = await _organization(db, owner)
        member = await _join(db, organization, OrgRoleName.MEMBER)
        await db.commit()
        meta = _meta(organization, None, member).model_copy(update={"personal": True})

        mine = await live_browse.access_for(meta, _token(member))

        assert mine is not None and mine.own and mine.control
        assert await live_browse.access_for(meta, _token(owner)) is None

    @pytest.mark.security
    async def test_a_member_with_nothing_to_do_with_the_run_sees_nothing(
        self, db: AsyncSession
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        agent = await _agent(db, organization, owner)
        bystander = await _join(db, organization, OrgRoleName.MEMBER)
        await db.commit()

        assert (
            await live_browse.access_for(_meta(organization, agent, owner), _token(bystander))
            is None
        )

    @pytest.mark.security
    async def test_another_organization_s_owner_sees_nothing(self, db: AsyncSession) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        agent = await _agent(db, organization, owner)
        stranger = await _person(db)
        await _organization(db, stranger)
        await db.commit()

        assert (
            await live_browse.access_for(_meta(organization, agent, owner), _token(stranger))
            is None
        )

    @pytest.mark.security
    async def test_a_token_that_is_not_a_signed_in_user_sees_nothing(
        self, db: AsyncSession
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        await db.commit()

        assert await live_browse.access_for(_meta(organization, None, owner), "forged") is None
