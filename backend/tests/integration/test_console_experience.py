"""PostgreSQL merges scoped preferences without replacing unrelated overrides."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import deployment_settings_repo, member_repo, organization_repo
from app.schemas.console_experience import (
    ChatHomeOverrides,
    ConsoleExperienceUpdate,
    OnboardingReminderOverrides,
)
from app.services.console_experience import ConsoleExperienceService
from app.services.organization import OrganizationService

pytestmark = pytest.mark.anyio


async def test_all_three_levels_merge_and_clear_without_crossing_memberships(
    db: AsyncSession,
) -> None:
    user = User(id=uuid4(), email="console@example.com", is_active=True)
    first = Organization(id=uuid4(), name="First", slug="console-first", created_by_user_id=user.id)
    second = Organization(
        id=uuid4(), name="Second", slug="console-second", created_by_user_id=user.id
    )
    db.add(user)
    await db.flush()
    db.add_all([first, second])
    await db.flush()
    db.add_all(
        [
            OrganizationMember(organization_id=first.id, user_id=user.id, role="owner"),
            OrganizationMember(organization_id=second.id, user_id=user.id, role="owner"),
        ]
    )
    await db.flush()
    service = ConsoleExperienceService(db)
    ctx = AuthContext(user_id=user.id, organization_id=first.id, role="owner")
    other = AuthContext(user_id=user.id, organization_id=second.id, role="owner")
    await deployment_settings_repo.upsert(db, update_data={"chat_home_available": {"inbox": False}})
    await deployment_settings_repo.upsert(
        db, update_data={"chat_home_available": {"feature_hints": False}}
    )
    deployment = await deployment_settings_repo.get(db)
    assert deployment is not None
    assert deployment.chat_home_available == {"inbox": False, "feature_hints": False}
    await organization_repo.set_chat_home_defaults(db, first, changes={"greeting": False})
    await organization_repo.set_chat_home_defaults(db, first, changes={"starters": False})
    assert first.chat_home_defaults == {"greeting": False, "starters": False}
    await service.update(
        ctx, ConsoleExperienceUpdate(preferences=ChatHomeOverrides(greeting=True, inbox=True))
    )
    result = await service.update(
        ctx, ConsoleExperienceUpdate(preferences=ChatHomeOverrides(starters=True))
    )
    assert result.effective.greeting and result.effective.starters
    assert result.effective.inbox is False and result.effective.feature_hints is False
    assert result.preferences.greeting is True and result.preferences.inbox is True
    assert (await service.read(other)).preferences == ChatHomeOverrides()
    assert (await service.read(other)).effective.greeting is True
    result = await service.update(
        ctx, ConsoleExperienceUpdate(preferences=ChatHomeOverrides(greeting=None))
    )
    assert result.preferences.greeting is None and result.preferences.starters is True
    assert result.effective.greeting is False
    await service.update(ctx, ConsoleExperienceUpdate(preferences=None))
    member = await member_repo.get(db, organization_id=first.id, user_id=user.id)
    assert member is not None and member.chat_home_preferences is None
    result = await service.update(
        ctx, ConsoleExperienceUpdate(preferences=ChatHomeOverrides(greeting=True))
    )
    assert result.preferences.greeting is True
    await organization_repo.set_chat_home_defaults(db, first, changes=None)
    await organization_repo.set_chat_home_defaults(db, first, changes={"greeting": False})
    assert first.chat_home_defaults == {"greeting": False}
    await deployment_settings_repo.upsert(db, update_data={"chat_home_available": None})
    await deployment_settings_repo.upsert(db, update_data={"chat_home_available": {"inbox": False}})
    assert (await service.read(ctx)).effective.inbox is False
    await deployment_settings_repo.upsert(db, update_data={"chat_home_available": {"inbox": None}})
    assert (await service.read(ctx)).effective.inbox is True

    await organization_repo.set_onboarding_reminders(db, first, changes={"enabled": False})
    await organization_repo.set_onboarding_reminders(db, first, changes={"snooze_days": 7})
    await service.update(
        ctx, ConsoleExperienceUpdate(reminders=OnboardingReminderOverrides(enabled=True))
    )
    result = await service.update(
        ctx, ConsoleExperienceUpdate(reminders=OnboardingReminderOverrides(snooze_days=3))
    )
    assert result.reminders.effective.enabled and result.reminders.effective.snooze_days == 3
    await deployment_settings_repo.upsert(db, update_data={"onboarding_reminders_available": False})
    assert not (await service.read(ctx)).reminders.effective.enabled
    await deployment_settings_repo.upsert(db, update_data={"onboarding_reminders_available": None})
    result = await service.update(
        ctx, ConsoleExperienceUpdate(reminders=OnboardingReminderOverrides(snooze_days=None))
    )
    assert result.reminders.effective.enabled and result.reminders.effective.snooze_days == 7
    assert (await service.read(other)).reminders.effective.snooze_days == 1
    await service.update(ctx, ConsoleExperienceUpdate(reminders=None))
    member = await member_repo.get(db, organization_id=first.id, user_id=user.id)
    assert member is not None and member.onboarding_reminders is None
    assert not (await service.read(ctx)).reminders.effective.enabled
    await organization_repo.set_onboarding_reminders(db, first, changes=None)
    await organization_repo.set_onboarding_reminders(db, first, changes={"snooze_days": 3})
    await service.update(
        ctx, ConsoleExperienceUpdate(reminders=OnboardingReminderOverrides(enabled=True))
    )
    assert (await service.read(ctx)).reminders.effective.snooze_days == 3

    readable = await OrganizationService(db).read_for_user(first.id, user.id)
    assert readable.onboarding_reminders is not None
    assert readable.onboarding_reminders.snooze_days == 3
    assert readable.chat_home_defaults is not None and readable.chat_home_defaults.greeting is False
