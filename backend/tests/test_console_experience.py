"""Chat-home presentation inherits without sharing one membership's choices."""

from dataclasses import dataclass
from itertools import product
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization, OrganizationMember
from app.repositories import deployment_settings_repo, member_repo, organization_repo
from app.schemas.console_experience import (
    ChatHomeOverrides,
    ConsoleExperienceUpdate,
    resolve_chat_home,
)
from app.schemas.organization import OrganizationUpdate
from app.services.console_experience import ConsoleExperienceService
from app.services.organization import OrganizationService

pytestmark = pytest.mark.anyio


@dataclass
class ExperienceFixture:
    ctx: AuthContext
    member: OrganizationMember
    org: Organization
    deployment: DeploymentSettings
    db: AsyncMock
    service: ConsoleExperienceService


@pytest.fixture
def experience(monkeypatch: pytest.MonkeyPatch) -> ExperienceFixture:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    member = OrganizationMember(
        user_id=ctx.subject_id, organization_id=ctx.organization_id, role="member"
    )
    org = Organization(
        id=ctx.organization_id, name="Acme", slug="acme", created_by_user_id=ctx.subject_id
    )
    deployment = DeploymentSettings()
    db = AsyncMock()
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=member))
    monkeypatch.setattr(member_repo, "set_console_preferences", AsyncMock(return_value=member))
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=org))
    monkeypatch.setattr(deployment_settings_repo, "get", AsyncMock(return_value=deployment))
    return ExperienceFixture(ctx, member, org, deployment, db, ConsoleExperienceService(db))


@pytest.mark.parametrize(
    ("ceiling", "default", "personal"), list(product((None, True, False), repeat=3))
)
def test_hierarchy_keeps_only_deployment_as_a_hard_ceiling(
    ceiling: bool | None, default: bool | None, personal: bool | None
) -> None:
    def choices(value: bool | None) -> ChatHomeOverrides:
        return ChatHomeOverrides(inbox=value, starters=value, greeting=value, feature_hints=value)

    result = resolve_chat_home(choices(ceiling), choices(default), choices(personal))
    expected = ceiling is not False and (
        personal if personal is not None else default if default is not None else True
    )
    assert set(result.model_dump().values()) == {expected}


def test_patch_distinguishes_omission_clear_and_false_and_rejects_unknown_or_coerced_fields() -> (
    None
):
    assert ChatHomeOverrides().changes() == {}
    assert ChatHomeOverrides(inbox=None, greeting=False).changes() == {
        "inbox": None,
        "greeting": False,
    }
    for value in ({"inbox": "false"}, {"theme": "dark"}, {"inbox": 1}):
        with pytest.raises(ValidationError):
            ChatHomeOverrides.model_validate(value)
    with pytest.raises(ValidationError):
        ConsoleExperienceUpdate.model_validate({"organization_id": str(uuid4())})


async def test_existing_null_rows_and_no_deployment_preserve_the_existing_home(
    experience: ExperienceFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deployment_settings_repo, "get", AsyncMock(return_value=None))
    result = await experience.service.read(experience.ctx)
    assert all(result.effective.model_dump().values())
    assert result.preferences.inbox is None
    member_repo.get_active.assert_awaited_once_with(
        experience.db,
        organization_id=experience.ctx.organization_id,
        user_id=experience.ctx.subject_id,
    )
    experience.db.flush.assert_not_awaited()


async def test_member_can_override_org_defaults_but_not_a_disabled_deployment_item(
    experience: ExperienceFixture,
) -> None:
    experience.deployment.chat_home_available = {"inbox": False}
    experience.org.chat_home_defaults = {"starters": False, "greeting": False}
    experience.member.chat_home_preferences = {"inbox": True, "starters": True}
    state = await experience.service.read(experience.ctx)
    assert state.effective.inbox is False and state.effective.starters is True
    assert state.effective.greeting is False and state.effective.feature_hints is True
    assert state.availability.starters is True


@pytest.mark.parametrize("fallback", (False, True))
async def test_no_subject_or_publisher_standin_cannot_read_personal_preferences(
    experience: ExperienceFixture, fallback: bool
) -> None:
    ctx = AuthContext(
        user_id=experience.ctx.user_id if fallback else None,
        organization_id=experience.ctx.organization_id,
        role="member",
        subject_is_publisher_fallback=fallback,
    )
    with pytest.raises(AuthorizationError):
        await experience.service.read(ctx)
    member_repo.get_active.assert_not_awaited()


async def test_missing_or_inactive_membership_and_missing_org_are_explicit(
    experience: ExperienceFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await experience.service.read(experience.ctx)
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=experience.member))
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await experience.service.read(experience.ctx)


async def test_partial_and_whole_reset_are_owned_by_the_current_membership(
    experience: ExperienceFixture,
) -> None:
    await experience.service.update(
        experience.ctx,
        ConsoleExperienceUpdate(preferences=ChatHomeOverrides(inbox=None, greeting=False)),
    )
    member_repo.set_console_preferences.assert_awaited_with(
        experience.db,
        organization_id=experience.ctx.organization_id,
        user_id=experience.ctx.subject_id,
        changes={"inbox": None, "greeting": False},
    )
    await experience.service.update(experience.ctx, ConsoleExperienceUpdate(preferences=None))
    member_repo.set_console_preferences.assert_awaited_with(
        experience.db,
        organization_id=experience.ctx.organization_id,
        user_id=experience.ctx.subject_id,
        changes=None,
    )
    with pytest.raises(BadRequestError):
        await experience.service.update(experience.ctx, ConsoleExperienceUpdate())


@pytest.mark.parametrize(("role", "scopes"), [("member", None), ("owner", {Perm.AGENTS_VIEW})])
async def test_org_defaults_require_org_settings_in_role_and_key_scope(
    experience: ExperienceFixture,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    scopes: set[Perm] | None,
) -> None:
    experience.member.role = role
    service = OrganizationService(experience.db)
    monkeypatch.setattr(
        service, "get_for_user", AsyncMock(return_value=(experience.org, experience.member))
    )
    change = AsyncMock()
    monkeypatch.setattr(organization_repo, "set_chat_home_defaults", change)
    with pytest.raises(AuthorizationError):
        await service.update(
            experience.ctx.organization_id,
            OrganizationUpdate(chat_home_defaults=ChatHomeOverrides(inbox=False)),
            experience.ctx.subject_id,
            key_scopes=frozenset(scopes) if scopes is not None else None,
        )
    change.assert_not_awaited()


async def test_org_admin_can_patch_or_clear_defaults_without_changing_other_settings(
    experience: ExperienceFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    experience.member.role = "owner"
    service = OrganizationService(experience.db)
    monkeypatch.setattr(
        service, "get_for_user", AsyncMock(return_value=(experience.org, experience.member))
    )
    change = AsyncMock(return_value=experience.org)
    monkeypatch.setattr(organization_repo, "set_chat_home_defaults", change)
    monkeypatch.setattr(organization_repo, "update", AsyncMock(return_value=experience.org))
    await service.update(
        experience.ctx.organization_id,
        OrganizationUpdate(chat_home_defaults=ChatHomeOverrides(starters=False)),
        experience.ctx.subject_id,
    )
    change.assert_awaited_with(experience.db, experience.org, changes={"starters": False})
    await service.update(
        experience.ctx.organization_id,
        OrganizationUpdate(chat_home_defaults=None),
        experience.ctx.subject_id,
    )
    change.assert_awaited_with(experience.db, experience.org, changes=None)


def test_reminder_frequency_is_bounded_and_inherits_without_accepting_boolean_days() -> None:
    from app.schemas.console_experience import (
        OnboardingReminderOverrides,
        resolve_onboarding_reminders,
    )

    assert OnboardingReminderOverrides().changes() == {}
    assert OnboardingReminderOverrides(enabled=None, snooze_days=3).changes() == {
        "enabled": None,
        "snooze_days": 3,
    }
    for days in (True, False, 0, 2, 4, 8, "3"):
        with pytest.raises(ValidationError):
            OnboardingReminderOverrides.model_validate({"snooze_days": days})
    result = resolve_onboarding_reminders(
        False,
        OnboardingReminderOverrides(enabled=False, snooze_days=7),
        OnboardingReminderOverrides(enabled=True, snooze_days=3),
    )
    assert result.effective.enabled is False and result.effective.snooze_days == 3
    result = resolve_onboarding_reminders(
        True,
        OnboardingReminderOverrides(enabled=False, snooze_days=7),
        OnboardingReminderOverrides(enabled=True),
    )
    assert result.effective.enabled is True and result.effective.snooze_days == 7
    assert (
        resolve_onboarding_reminders(
            None, OnboardingReminderOverrides(), OnboardingReminderOverrides()
        ).effective.snooze_days
        == 1
    )


async def test_reminder_patch_and_reset_are_scoped_and_do_not_change_chat_preferences(
    experience: ExperienceFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.console_experience import OnboardingReminderOverrides

    update = AsyncMock(return_value=experience.member)
    monkeypatch.setattr(member_repo, "set_onboarding_reminders", update)
    await experience.service.update(
        experience.ctx,
        ConsoleExperienceUpdate(
            reminders=OnboardingReminderOverrides(enabled=False, snooze_days=7)
        ),
    )
    update.assert_awaited_with(
        experience.db,
        organization_id=experience.ctx.organization_id,
        user_id=experience.ctx.subject_id,
        changes={"enabled": False, "snooze_days": 7},
    )
    member_repo.set_console_preferences.assert_not_awaited()
    await experience.service.update(experience.ctx, ConsoleExperienceUpdate(reminders=None))
    update.assert_awaited_with(
        experience.db,
        organization_id=experience.ctx.organization_id,
        user_id=experience.ctx.subject_id,
        changes=None,
    )


async def test_org_reminder_defaults_use_the_same_settings_authority(
    experience: ExperienceFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.console_experience import OnboardingReminderOverrides

    experience.member.role = "owner"
    service = OrganizationService(experience.db)
    monkeypatch.setattr(
        service, "get_for_user", AsyncMock(return_value=(experience.org, experience.member))
    )
    change = AsyncMock(return_value=experience.org)
    monkeypatch.setattr(organization_repo, "set_onboarding_reminders", change)
    monkeypatch.setattr(organization_repo, "update", AsyncMock(return_value=experience.org))
    await service.update(
        experience.ctx.organization_id,
        OrganizationUpdate(
            onboarding_reminders=OnboardingReminderOverrides(enabled=False, snooze_days=7)
        ),
        experience.ctx.subject_id,
    )
    change.assert_awaited_with(
        experience.db, experience.org, changes={"enabled": False, "snooze_days": 7}
    )
    await service.update(
        experience.ctx.organization_id,
        OrganizationUpdate(onboarding_reminders=None),
        experience.ctx.subject_id,
    )
    change.assert_awaited_with(experience.db, experience.org, changes=None)
