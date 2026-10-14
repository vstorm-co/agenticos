"""System agents and the AI assistance switch, against a real database.

What the seed writes is decided by constraints the unit suite cannot see: the
per-organization uniqueness of a system key, a slug a person's own agent already
holds, which profile is "the oldest" when two share a timestamp.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.agents.spec import AgentSpec
from app.agents.system_agents import JUDGE
from app.core.exceptions import (
    AiAssistanceDisabledError,
    AuthorizationError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import agent_repo
from app.schemas.organization import OrganizationCreate, OrganizationUpdate
from app.services.agent_registry import AgentRegistryService
from app.services.ai_assistance import AiAssistanceService
from app.services.organization import OrganizationService
from app.services.system_agents import SystemAgentService

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


async def _organization(db, *, with_owner: bool = True) -> tuple[Organization, User]:
    user = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(organization)
    await db.flush()
    if with_owner:
        await _member(db, organization, user, OrgRoleName.OWNER)
    return organization, user


async def _member(db, organization: Organization, user: User, role: OrgRoleName) -> None:
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=organization.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db.flush()


async def _profile(db, organization: Organization, *, label: str, created_at: datetime):
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=organization.id,
        label=label,
        provider="openai",
        model="gpt-4.1",
        created_at=created_at,
    )
    db.add(profile)
    await db.flush()
    return profile


class TestSeeding:
    async def test_a_new_organization_starts_with_the_judge_as_a_draft(self, db) -> None:
        """A new organization has no model yet, so the judge cannot be published."""
        owner = await _user(db)
        organization = await OrganizationService(db).create(
            OrganizationCreate(name="Fresh org"), owner.id
        )

        judge = await agent_repo.get_system(db, organization_id=organization.id, key=JUDGE.key)

        assert judge is not None
        assert judge.name == JUDGE.name
        assert judge.status == AgentStatus.DRAFT.value
        assert judge.current_version_id is None
        assert judge.visibility == Visibility.ORG.value
        assert judge.owner_user_id == owner.id
        spec = AgentSpec.model_validate(judge.draft_spec)
        assert spec.instructions == JUDGE.instructions
        assert spec.budget is not None
        assert spec.budget.monthly_usd == JUDGE.monthly_usd

    async def test_a_personal_organization_is_seeded_too(self, db) -> None:
        user = await _user(db)
        organization = await OrganizationService(db).create_personal_org(user.id, user.email)

        assert await agent_repo.get_system(db, organization_id=organization.id, key=JUDGE.key)

    async def test_ensure_seeds_an_organization_created_before_the_judge_existed(self, db) -> None:
        organization, _ = await _organization(db)
        service = SystemAgentService(db)

        first = await service.ensure(organization_id=organization.id, key=JUDGE.key)
        again = await service.ensure(organization_id=organization.id, key=JUDGE.key)

        assert again.id == first.id
        rows = await db.scalars(
            select(Agent).where(
                Agent.organization_id == organization.id, Agent.system_key == JUDGE.key
            )
        )
        assert len(list(rows)) == 1

    async def test_with_a_model_it_publishes_on_the_oldest_profile(self, db) -> None:
        """The oldest by creation, then id - the same answer whichever request seeds."""
        organization, _ = await _organization(db)
        now = datetime.now(UTC)
        await _profile(db, organization, label="A newer one", created_at=now)
        oldest = await _profile(db, organization, label="Z oldest", created_at=now - timedelta(1))

        judge = await SystemAgentService(db).ensure(organization_id=organization.id, key=JUDGE.key)

        assert judge.status == AgentStatus.PUBLISHED.value
        version = await db.get(AgentVersion, judge.current_version_id)
        assert version is not None
        assert version.spec["model_profile_id"] == str(oldest.id)

    async def test_a_name_a_person_already_uses_is_left_to_them(self, db) -> None:
        organization, owner = await _organization(db)
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
        theirs = await AgentRegistryService(db).create(ctx, AgentSpec(name=JUDGE.name))

        judge = await SystemAgentService(db).ensure(organization_id=organization.id, key=JUDGE.key)

        assert judge.id != theirs.id
        assert judge.name == f"{JUDGE.name} (system)"
        await db.refresh(theirs)
        assert theirs.system_key is None

    async def test_an_organization_without_an_owner_cannot_be_seeded(self, db) -> None:
        organization, _ = await _organization(db, with_owner=False)

        with pytest.raises(SystemAgentUnavailableError) as raised:
            await SystemAgentService(db).ensure(organization_id=organization.id, key=JUDGE.key)

        assert raised.value.reason == "not_seeded"
        assert (
            await agent_repo.get_system(db, organization_id=organization.id, key=JUDGE.key) is None
        )

    async def test_one_organization_holds_one_agent_per_key(self, db) -> None:
        organization, _ = await _organization(db)
        await SystemAgentService(db).ensure(organization_id=organization.id, key=JUDGE.key)
        twin = Agent(
            id=uuid.uuid4(),
            organization_id=organization.id,
            slug="judge-twin",
            name="Judge twin",
            draft_spec={},
            visibility=Visibility.ORG.value,
            system_key=JUDGE.key,
        )
        db.add(twin)

        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_another_organization_does_not_see_this_ones_judge(self, db) -> None:
        mine, _ = await _organization(db)
        theirs, _ = await _organization(db)
        await SystemAgentService(db).ensure(organization_id=mine.id, key=JUDGE.key)

        assert await agent_repo.get_system(db, organization_id=theirs.id, key=JUDGE.key) is None

    async def test_the_system_listing_marks_the_judge_as_a_system_agent(self, db) -> None:
        organization, owner = await _organization(db)
        await SystemAgentService(db).ensure(organization_id=organization.id, key=JUDGE.key)
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)

        listed, _ = await AgentRegistryService(db).list_agents(ctx, system=True)

        assert [agent.system_key for agent in listed] == [JUDGE.key]


class TestTheSwitch:
    async def test_an_organization_starts_with_ai_assistance_off(self, db) -> None:
        organization, _ = await _organization(db)

        assert not await AiAssistanceService(db).is_enabled(organization_id=organization.id)

    async def test_an_organization_the_migration_finds_has_it_off(self, db) -> None:
        """The column's own default, as a row written without it gets it."""
        user = await _user(db)
        organization_id = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, created_by_user_id, is_personal) "
                "VALUES (:id, 'Old', :slug, :user, false)"
            ),
            {"id": organization_id, "slug": f"old-{organization_id.hex[:8]}", "user": user.id},
        )

        assert not await AiAssistanceService(db).is_enabled(organization_id=organization_id)

    async def test_switched_off_the_service_refuses(self, db) -> None:
        organization, owner = await _organization(db)
        await OrganizationService(db).update(
            organization.id, OrganizationUpdate(ai_assistance_enabled=False), owner.id
        )

        with pytest.raises(AiAssistanceDisabledError):
            await AiAssistanceService(db).require_enabled(organization_id=organization.id)

    async def test_switching_it_is_audited_and_a_repeat_is_not(self, db) -> None:
        organization, owner = await _organization(db)
        service = OrganizationService(db)

        await service.update(
            organization.id, OrganizationUpdate(ai_assistance_enabled=True), owner.id
        )
        await service.update(
            organization.id, OrganizationUpdate(ai_assistance_enabled=True), owner.id
        )
        await service.update(
            organization.id, OrganizationUpdate(ai_assistance_enabled=False), owner.id
        )

        entries = (
            await db.scalars(
                select(AppAdminAuditLog)
                .where(
                    AppAdminAuditLog.organization_id == organization.id,
                    AppAdminAuditLog.action == "organization.ai_assistance",
                )
                .order_by(AppAdminAuditLog.created_at, AppAdminAuditLog.id)
            )
        ).all()
        assert sorted(entry.details["enabled"] for entry in entries) == [False, True]
        assert {entry.actor_user_id for entry in entries} == {owner.id}

    async def test_an_admin_switches_it_on(self, db) -> None:
        organization, _ = await _organization(db)
        admin = await _user(db)
        await _member(db, organization, admin, OrgRoleName.ADMIN)

        updated = await OrganizationService(db).update(
            organization.id, OrganizationUpdate(ai_assistance_enabled=True), admin.id
        )

        assert updated.ai_assistance_enabled is True

    async def test_a_member_without_org_settings_cannot_switch_it(self, db) -> None:
        organization, _ = await _organization(db)
        member = await _user(db)
        await _member(db, organization, member, OrgRoleName.MEMBER)

        with pytest.raises(AuthorizationError):
            await OrganizationService(db).update(
                organization.id, OrganizationUpdate(ai_assistance_enabled=True), member.id
            )

        await db.refresh(organization)
        assert organization.ai_assistance_enabled is False

    async def test_renaming_the_organization_leaves_the_switch_alone(self, db) -> None:
        organization, owner = await _organization(db)
        organization.ai_assistance_enabled = True
        await db.flush()

        updated = await OrganizationService(db).update(
            organization.id, OrganizationUpdate(name="Renamed"), owner.id
        )

        assert updated.ai_assistance_enabled is True
