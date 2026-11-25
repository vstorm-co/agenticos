"""Resolve presentation independently of resource permissions and agent behavior."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.chat_costs import chat_cost_policy
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.organization import OrganizationMember
from app.repositories import deployment_settings_repo, member_repo, organization_repo
from app.schemas.console_experience import (
    ChatHomeOverrides,
    ConsoleExperienceRead,
    ConsoleExperienceUpdate,
    OnboardingReminderOverrides,
    resolve_chat_costs,
    resolve_chat_home,
    resolve_onboarding_reminders,
)


class ConsoleExperienceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _member(self, ctx: AuthContext) -> OrganizationMember:
        if ctx.is_anonymous or ctx.subject_is_publisher_fallback:
            raise AuthorizationError(
                message="Console preferences require a personal account", details={}
            )
        member = await member_repo.get_active(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )
        if member is None:
            raise NotFoundError(message="Organization membership not found", details={})
        return member

    async def read(self, ctx: AuthContext) -> ConsoleExperienceRead:
        member = await self._member(ctx)
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if organization is None:
            raise NotFoundError(message="Organization not found", details={})
        deployment = await deployment_settings_repo.get(self.db)
        available = ChatHomeOverrides.model_validate(
            deployment.chat_home_available or {} if deployment else {}
        )
        defaults = ChatHomeOverrides.model_validate(organization.chat_home_defaults or {})
        preferences = ChatHomeOverrides.model_validate(member.chat_home_preferences or {})
        return ConsoleExperienceRead(
            costs=resolve_chat_costs(
                deployment.chat_costs_available if deployment else None,
                chat_cost_policy(organization.chat_cost_visibility),
                member.chat_costs_visible,
                eligible=True,
                spend_privileged=ctx.has(Perm.BUDGETS_MANAGE) or ctx.has(Perm.RUNS_VIEW),
            ),
            reminders=resolve_onboarding_reminders(
                deployment.onboarding_reminders_available if deployment else None,
                OnboardingReminderOverrides.model_validate(organization.onboarding_reminders or {}),
                OnboardingReminderOverrides.model_validate(member.onboarding_reminders or {}),
            ),
            availability=resolve_chat_home(available, ChatHomeOverrides(), ChatHomeOverrides()),
            organization_defaults=defaults,
            preferences=preferences,
            effective=resolve_chat_home(available, defaults, preferences),
        )

    async def update(
        self, ctx: AuthContext, data: ConsoleExperienceUpdate
    ) -> ConsoleExperienceRead:
        member = await self._member(ctx)
        if not data.model_fields_set:
            raise BadRequestError(message="Nothing to change", details={})
        if "chat_costs" in data.model_fields_set:
            updated_member = await member_repo.set_chat_cost_preference(
                self.db,
                organization_id=ctx.organization_id,
                user_id=member.user_id,
                visible=data.chat_costs,
            )
            if updated_member is None:
                raise NotFoundError(message="Organization membership not found", details={})
        if "preferences" in data.model_fields_set:
            await member_repo.set_console_preferences(
                self.db,
                organization_id=ctx.organization_id,
                user_id=member.user_id,
                changes=data.preferences.changes() if data.preferences is not None else None,
            )
        if "reminders" in data.model_fields_set:
            await member_repo.set_onboarding_reminders(
                self.db,
                organization_id=ctx.organization_id,
                user_id=member.user_id,
                changes=data.reminders.changes() if data.reminders is not None else None,
            )
        return await self.read(ctx)
