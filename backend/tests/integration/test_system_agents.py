"""System agents and the AI assistance switch, against a real database.

What the seed writes is decided by constraints the unit suite cannot see: the
per-organization uniqueness of a system key, a slug a person's own agent already
holds, which profile is "the oldest" when two share a timestamp.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.agents.spec import AgentSpec
from app.agents.system_agents import IMPROVER, JUDGE
from app.core.exceptions import (
    AiAssistanceDisabledError,
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.agent import Agent, AgentKind, AgentStatus, AgentVersion
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import agent_repo
from app.schemas.agent import SystemAgentCreate
from app.schemas.organization import OrganizationCreate, OrganizationUpdate
from app.services.agent_registry import AgentRegistryService
from app.services.ai_assistance import AiAssistanceService
from app.services.model_profile import ModelProfileService
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


async def _secret(db, organization: Organization) -> OrganizationSecret:
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-test-key"), scope=VaultScope.organization(organization.id)
    )
    secret = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=organization.id,
        name="Key",
        purpose="openai",
        visibility="org",
        kind=SecretKind.API_KEY.value,
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
    )
    db.add(secret)
    await db.flush()
    return secret


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

    async def test_the_organization_s_first_model_publishes_the_waiting_judge(
        self, db, monkeypatch
    ) -> None:
        """Seeded before any model exists, the judge works once the first one is added."""
        monkeypatch.setattr(ModelProfileService, "_context_length", AsyncMock(return_value=None))
        owner = await _user(db)
        organization = await OrganizationService(db).create(
            OrganizationCreate(name="Fresh org"), owner.id
        )
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
        secret = await _secret(db, organization)

        profile = await ModelProfileService(db).create_profile(
            ctx, label="Default", provider="openai", model="gpt-4.1", secret_id=secret.id
        )

        judge = await agent_repo.get_system(db, organization_id=organization.id, key=JUDGE.key)
        assert judge is not None and judge.current_version_id is not None
        assert judge.status == AgentStatus.PUBLISHED.value
        version = await db.get(AgentVersion, judge.current_version_id)
        assert version is not None
        assert version.spec["model_profile_id"] == str(profile.id)
        assert version.spec["model_settings"] == {"temperature": 0.0}
        [entry] = list(
            await db.scalars(
                select(AppAdminAuditLog).where(
                    AppAdminAuditLog.organization_id == organization.id,
                    AppAdminAuditLog.action == "system_agent.published",
                    AppAdminAuditLog.target_id == str(judge.id),
                )
            )
        )
        assert entry.actor_user_id is None
        improver = await agent_repo.get_system(
            db, organization_id=organization.id, key=IMPROVER.key
        )
        assert improver is not None and improver.current_version_id is not None
        assert entry.details == {
            "key": JUDGE.key,
            "model_profile_id": str(profile.id),
            "model": "Default",
        }

    async def test_a_judge_still_waiting_is_published_when_it_is_next_needed(self, db) -> None:
        owner = await _user(db)
        organization = await OrganizationService(db).create(
            OrganizationCreate(name="Fresh org"), owner.id
        )
        oldest = await _profile(db, organization, label="Default", created_at=datetime.now(UTC))

        judge = await SystemAgentService(db).ensure(organization_id=organization.id, key=JUDGE.key)

        assert judge.current_version_id is not None
        version = await db.get(AgentVersion, judge.current_version_id)
        assert version is not None and version.spec["model_profile_id"] == str(oldest.id)

    async def test_a_draft_somebody_gave_a_model_is_left_to_them(self, db) -> None:
        owner = await _user(db)
        organization = await OrganizationService(db).create(
            OrganizationCreate(name="Fresh org"), owner.id
        )
        picked = await _profile(db, organization, label="Picked", created_at=datetime.now(UTC))
        judge = await agent_repo.get_system(db, organization_id=organization.id, key=JUDGE.key)
        assert judge is not None
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
        spec = AgentSpec.model_validate(judge.draft_spec)
        await AgentRegistryService(db).save_draft(
            ctx, judge.id, spec.model_copy(update={"model_profile_id": picked.id})
        )

        await SystemAgentService(db).adopt_model(organization_id=organization.id)

        assert judge.current_version_id is None

    async def test_a_draft_somebody_edited_waits_for_them_even_without_a_model(self, db) -> None:
        owner = await _user(db)
        organization = await OrganizationService(db).create(
            OrganizationCreate(name="Fresh org"), owner.id
        )
        judge = await agent_repo.get_system(db, organization_id=organization.id, key=JUDGE.key)
        assert judge is not None
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
        spec = AgentSpec.model_validate(judge.draft_spec)
        await AgentRegistryService(db).save_draft(
            ctx, judge.id, spec.model_copy(update={"instructions": "Grade harshly."})
        )
        await _profile(db, organization, label="Default", created_at=datetime.now(UTC))

        await SystemAgentService(db).adopt_model(organization_id=organization.id)

        assert judge.current_version_id is None

    async def test_without_a_model_or_an_owner_the_judge_keeps_waiting(self, db) -> None:
        organization, _ = await _organization(db, with_owner=False)
        service = SystemAgentService(db)
        owner = await _user(db)
        await _member(db, organization, owner, OrgRoleName.OWNER)
        judge = await service.ensure(organization_id=organization.id, key=JUDGE.key)
        await db.execute(
            text("DELETE FROM organization_members WHERE organization_id = :org"),
            {"org": organization.id},
        )
        await _profile(db, organization, label="Default", created_at=datetime.now(UTC))

        await service.adopt_model(organization_id=organization.id)
        lonely, _ = await _organization(db)
        await service.adopt_model(organization_id=lonely.id)

        assert judge.current_version_id is None

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
        assert version.spec["model_settings"] == {"temperature": 0.0}

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

    async def test_the_judges_listing_marks_the_seeded_judge(self, db) -> None:
        organization, owner = await _organization(db)
        await SystemAgentService(db).ensure(organization_id=organization.id, key=JUDGE.key)
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)

        listed, _ = await AgentRegistryService(db).list_agents(ctx, kind=AgentKind.JUDGE)

        assert [(agent.system_key, agent.kind) for agent in listed] == [
            (JUDGE.key, AgentKind.JUDGE)
        ]


class TestTheGradingModel:
    async def test_it_is_set_audited_and_cleared_by_whoever_holds_the_settings(self, db) -> None:
        organization, owner = await _organization(db)
        grading = await _profile(db, organization, label="Grading", created_at=datetime.now(UTC))
        service = OrganizationService(db)

        await service.update(
            organization.id, OrganizationUpdate(grading_model_profile_id=grading.id), owner.id
        )
        assert organization.grading_model_profile_id == grading.id
        await service.update(
            organization.id, OrganizationUpdate(grading_model_profile_id=grading.id), owner.id
        )
        await service.update(organization.id, OrganizationUpdate(name="Renamed"), owner.id)
        assert organization.grading_model_profile_id == grading.id
        await service.update(
            organization.id, OrganizationUpdate(grading_model_profile_id=None), owner.id
        )

        assert organization.grading_model_profile_id is None
        audited = await db.scalars(
            select(AppAdminAuditLog.details).where(
                AppAdminAuditLog.action == "organization.grading_model"
            )
        )
        assert [entry["model_profile_id"] for entry in audited] == [str(grading.id), None]

    async def test_a_model_of_another_organization_or_one_that_cannot_chat_is_refused(
        self, db
    ) -> None:
        organization, owner = await _organization(db)
        other, _ = await _organization(db)
        theirs = await _profile(db, other, label="Theirs", created_at=datetime.now(UTC))
        speech = await _profile(db, organization, label="Speech", created_at=datetime.now(UTC))
        speech.model = "tts-1"
        await db.flush()
        service = OrganizationService(db)

        for profile, message in ((theirs, "not one of this organization's"), (speech, "")):
            with pytest.raises(BadRequestError, match=message):
                await service.update(
                    organization.id,
                    OrganizationUpdate(grading_model_profile_id=profile.id),
                    owner.id,
                )
        assert organization.grading_model_profile_id is None

    async def test_a_member_without_the_settings_cannot_set_it(self, db) -> None:
        organization, _ = await _organization(db)
        member = await _user(db)
        await _member(db, organization, member, OrgRoleName.MEMBER)
        grading = await _profile(db, organization, label="Grading", created_at=datetime.now(UTC))

        with pytest.raises(AuthorizationError):
            await OrganizationService(db).update(
                organization.id, OrganizationUpdate(grading_model_profile_id=grading.id), member.id
            )


class TestADatasetsOwnJudge:
    async def test_it_is_a_judge_without_the_key_published_on_the_oldest_model(self, db) -> None:
        organization, owner = await _organization(db)
        oldest = await _profile(db, organization, label="Only", created_at=datetime.now(UTC))
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)

        judge = await SystemAgentService(db).create_judge(
            ctx,
            name="Refunds judge",
            description="Grades refunds.",
            visibility=Visibility.ORG,
            instructions="Be strict.",
        )

        assert (judge.kind, judge.system_key, judge.status) == (
            AgentKind.JUDGE.value,
            None,
            AgentStatus.PUBLISHED.value,
        )
        version = await db.get(AgentVersion, judge.current_version_id)
        assert version is not None
        assert version.spec["model_profile_id"] == str(oldest.id)
        assert version.spec["instructions"] == "Be strict."
        assert version.spec["budget"]["monthly_usd"] == JUDGE.monthly_usd

    async def test_unpicked_it_runs_on_the_organization_s_grading_model(self, db) -> None:
        organization, owner = await _organization(db)
        now = datetime.now(UTC)
        await _profile(db, organization, label="Oldest", created_at=now - timedelta(1))
        grading = await _profile(db, organization, label="Grading", created_at=now)
        organization.grading_model_profile_id = grading.id
        await db.flush()
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)

        judge = await SystemAgentService(db).create_judge(
            ctx,
            visibility=Visibility.ORG,
            name="Refunds judge",
            description="Grades refunds.",
            instructions="Be strict.",
        )

        version = await db.get(AgentVersion, judge.current_version_id)
        assert version is not None
        assert version.spec["model_profile_id"] == str(grading.id)

    async def test_it_runs_on_the_model_picked_for_it(self, db) -> None:
        organization, owner = await _organization(db)
        now = datetime.now(UTC)
        await _profile(db, organization, label="Oldest", created_at=now - timedelta(1))
        picked = await _profile(db, organization, label="Picked", created_at=now)
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)

        judge = await SystemAgentService(db).create_judge(
            ctx,
            visibility=Visibility.ORG,
            name="Refunds judge",
            description="Grades refunds.",
            instructions="Be strict.",
            model_profile_id=picked.id,
        )

        version = await db.get(AgentVersion, judge.current_version_id)
        assert version is not None
        assert version.spec["model_profile_id"] == str(picked.id)

    async def test_without_a_model_it_stays_a_draft(self, db) -> None:
        organization, owner = await _organization(db)
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)

        judge = await SystemAgentService(db).create_judge(
            ctx,
            name="Refunds judge",
            description="Grades refunds.",
            visibility=Visibility.ORG,
            instructions="Be strict.",
        )

        assert judge.status == AgentStatus.DRAFT.value

    async def test_a_model_of_another_organization_is_refused(self, db) -> None:
        organization, owner = await _organization(db)
        other, _ = await _organization(db)
        theirs = await _profile(db, other, label="Theirs", created_at=datetime.now(UTC))
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)

        with pytest.raises(NotFoundError):
            await SystemAgentService(db).create_judge(
                ctx,
                visibility=Visibility.ORG,
                name="Refunds judge",
                description="Grades refunds.",
                instructions="Be strict.",
                model_profile_id=theirs.id,
            )


class TestASystemAgentFromNewAgent:
    async def test_a_judge_starts_from_its_definition_and_publishes(self, db) -> None:
        organization, owner = await _organization(db)
        oldest = await _profile(db, organization, label="Only", created_at=datetime.now(UTC))
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)

        judge = await SystemAgentService(db).create_from_console(
            ctx, SystemAgentCreate(kind="judge", name="Second opinion")
        )

        assert (judge.kind, judge.system_key, judge.status, judge.name) == (
            AgentKind.JUDGE.value,
            None,
            AgentStatus.PUBLISHED.value,
            "Second opinion",
        )
        version = await db.get(AgentVersion, judge.current_version_id)
        assert version is not None
        assert (version.spec["model_profile_id"], version.spec["instructions"]) == (
            str(oldest.id),
            JUDGE.instructions,
        )
        assert version.spec["description"] == JUDGE.description
        assert version.spec["model_settings"]["temperature"] == JUDGE.temperature
        assert version.spec["budget"]["monthly_usd"] == JUDGE.monthly_usd

    async def test_a_member_who_may_not_publish_gets_a_draft(self, db) -> None:
        organization, _ = await _organization(db)
        await _profile(db, organization, label="Only", created_at=datetime.now(UTC))
        member = await _user(db)
        await _member(db, organization, member, OrgRoleName.MEMBER)
        ctx = AuthContext(
            user_id=member.id, organization_id=organization.id, role=OrgRoleName.MEMBER
        )

        judge = await SystemAgentService(db).create_from_console(
            ctx, SystemAgentCreate(kind="judge", name="Mine")
        )

        assert (judge.kind, judge.status) == (AgentKind.JUDGE.value, AgentStatus.DRAFT.value)

    @pytest.mark.parametrize("kind", ["generator", "drafter", "classifier", "improver"])
    async def test_each_selectable_kind_can_be_created_from_new_agent(self, db, kind) -> None:
        organization, owner = await _organization(db)
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
        created = await SystemAgentService(db).create_from_console(
            ctx, SystemAgentCreate(kind=kind, name="Another")
        )
        assert created.kind == kind
        assert created.system_key is None
        assert created.status == "draft"

    async def test_a_taken_name_or_another_organization_s_model_is_refused(self, db) -> None:
        organization, owner = await _organization(db)
        other, _ = await _organization(db)
        theirs = await _profile(db, other, label="Theirs", created_at=datetime.now(UTC))
        ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
        service = SystemAgentService(db)
        await service.create_from_console(ctx, SystemAgentCreate(kind="judge", name="Grader"))

        with pytest.raises(AlreadyExistsError):
            await service.create_from_console(ctx, SystemAgentCreate(kind="judge", name="Grader"))
        with pytest.raises(NotFoundError):
            await service.create_from_console(
                ctx, SystemAgentCreate(kind="judge", name="Other", model_profile_id=theirs.id)
            )


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
