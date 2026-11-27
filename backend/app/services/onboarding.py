"""One start contract for web, invitations and native clients; never calls a model."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import get_args
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, BudgetSpec
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import AgentStatus
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization, OrganizationMember, OrganizationOnboardingStep
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import (
    agent_repo,
    deployment_settings_repo,
    member_repo,
    onboarding_repo,
    organization_assistant_repo,
    organization_repo,
    user_repo,
)
from app.schemas.console_experience import OnboardingReminderOverrides, resolve_onboarding_reminders
from app.schemas.onboarding import (
    MemberStartRead,
    OnboardingAgent,
    OnboardingRead,
    OnboardingScope,
    OnboardingScopeRead,
    OnboardingScopeUpdate,
    OnboardingUpdate,
)
from app.services.agent_registry import AgentRegistryService
from app.services.model_profile import ModelProfileService, choosable_for_others
from app.services.shipped_agents import ShippedAgentService

STARTER_NAME = "Getting started"
STARTER_SLUG = "getting-started"


class OnboardingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)

    async def _member(self, ctx: AuthContext, *, for_update: bool = False) -> OrganizationMember:
        if ctx.is_anonymous:
            raise AuthorizationError(
                message="Start preferences require a personal account", details={}
            )
        member = await member_repo.get_active(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )
        if member is None:
            raise NotFoundError(message="Organization membership not found", details={})
        if for_update:
            locked = await member_repo.get(
                self.db,
                organization_id=ctx.organization_id,
                user_id=ctx.subject_id,
                for_update=True,
            )
            if locked is None:
                raise NotFoundError(message="Organization membership not found", details={})
            return locked
        return member

    async def state(self, ctx: AuthContext) -> OnboardingRead:
        member = await self._member(ctx)
        org = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if org is None:
            raise NotFoundError(message="Organization not found", details={})
        agents = await self._agents(ctx)
        result = await onboarding_repo.latest_result(
            self.db, organization_id=ctx.organization_id, user_id=member.user_id
        )
        person = await user_repo.get_by_id(self.db, member.user_id)
        owner_id = await member_repo.first_owner_id(self.db, organization_id=ctx.organization_id)
        owner = await user_repo.get_by_id(self.db, owner_id) if owner_id is not None else None
        completed_at = onboarding_repo.effective_completed_at(
            member, person.onboarding_completed_at if person else None
        )
        completed = completed_at is not None
        deployment = await deployment_settings_repo.get(self.db)
        reminders = resolve_onboarding_reminders(
            deployment.onboarding_reminders_available if deployment else None,
            OnboardingReminderOverrides.model_validate(org.onboarding_reminders or {}),
            OnboardingReminderOverrides.model_validate(member.onboarding_reminders or {}),
        )
        snoozed_until = (
            member.onboarding_dismissed_at + timedelta(days=reminders.effective.snooze_days)
            if member.onboarding_dismissed_at is not None
            else None
        )
        if completed or (snoozed_until is not None and snoozed_until <= datetime.now(UTC)):
            snoozed_until = None
        scopes = self._scopes(ctx, member, person, org, deployment, completed_at)
        active_scope = next(
            (
                scope.scope
                for scope in scopes
                if scope.applicable
                and not scope.completed
                and (scope.scope != "personal" or snoozed_until is None)
            ),
            None,
        )
        return OnboardingRead(
            scopes=scopes,
            active_scope=active_scope,
            organization_id=org.id,
            organization_name=org.name,
            goal=member.onboarding_goal,
            dismissed=completed or snoozed_until is not None,
            completed=completed,
            completed_at=completed_at,
            current_step=None if completed else member.onboarding_current_step,
            updated_at=member.onboarding_updated_at,
            snoozed_until=snoozed_until,
            can_prepare=ctx.has(Perm.AGENTS_EDIT) and ctx.has(Perm.AGENTS_PUBLISH),
            can_configure_model=ctx.has(Perm.CONNECTIONS_MANAGE),
            support_email=owner.email if owner is not None else None,
            agents=agents,
            setup_agent=await self._setup_agent(ctx) if not agents else None,
            latest_conversation_id=result.conversation_id if result is not None else None,
            latest_completed_at=result.ended_at if result is not None else None,
            has_result=result is not None,
            has_activity=result is not None
            or await onboarding_repo.has_activity(
                self.db, organization_id=ctx.organization_id, user_id=member.user_id
            ),
        )

    async def deployment_state(self, actor: User) -> OnboardingRead:
        """The app administrator's installation start before any organization exists."""
        if not actor.is_active or not actor.is_app_admin:
            raise AuthorizationError(
                message="Deployment setup requires app administrator access", details={}
            )
        row = await deployment_settings_repo.get(self.db)
        completed_at = row.onboarding_completed_at if row is not None else None
        return OnboardingRead(
            organization_id=None,
            organization_name=None,
            goal=None,
            dismissed=False,
            can_prepare=False,
            can_configure_model=False,
            support_email=None,
            agents=[],
            latest_conversation_id=None,
            latest_completed_at=None,
            has_result=False,
            scopes=[
                OnboardingScopeRead(
                    scope="deployment",
                    applicable=True,
                    completed=completed_at is not None,
                    completed_at=completed_at,
                    current_step=row.onboarding_current_step
                    if row is not None and completed_at is None
                    else None,
                    updated_at=row.onboarding_updated_at if row is not None else None,
                ),
                OnboardingScopeRead(scope="organization", applicable=False),
                OnboardingScopeRead(scope="personal", applicable=False),
            ],
            active_scope="deployment" if completed_at is None else None,
        )

    async def update_deployment(self, actor: User, data: OnboardingScopeUpdate) -> OnboardingRead:
        """Update installation setup without requiring a first organization."""
        if not actor.is_active or not actor.is_app_admin:
            raise AuthorizationError(
                message="Deployment setup requires app administrator access", details={}
            )
        if data.current_step is not None and data.current_step != "admin.deployment":
            raise BadRequestError(
                message="This screen does not belong to deployment setup", details={}
            )
        row = await onboarding_repo.deployment_for_update(self.db)
        fresh_actor = await onboarding_repo.deployment_actor(self.db, actor.id)
        if fresh_actor is None or not fresh_actor.is_active or not fresh_actor.is_app_admin:
            raise AuthorizationError(
                message="Deployment setup requires app administrator access", details={}
            )
        await onboarding_repo.save_shared(self.db, row=row, data=data)
        return await self.deployment_state(fresh_actor)

    @staticmethod
    def _scope_context(
        ctx: AuthContext, member: OrganizationMember, person: User | None
    ) -> AuthContext:
        # AuthContext is request-scoped; shared progress rechecks live identity and membership.
        return replace(
            ctx, role=member.role, is_app_admin=person is not None and person.is_app_admin is True
        )

    @staticmethod
    def _session_scope(ctx: AuthContext) -> bool:
        return (
            ctx.api_key_id is None
            and ctx.key_scopes is None
            and not ctx.subject_is_publisher_fallback
        )

    def _scopes(
        self,
        ctx: AuthContext,
        member: OrganizationMember,
        person: User | None,
        organization: Organization,
        deployment: DeploymentSettings | None,
        personal_completed_at: datetime | None,
    ) -> list[OnboardingScopeRead]:
        fresh = self._scope_context(ctx, member, person)
        session = self._session_scope(ctx)
        scopes: list[OnboardingScopeRead] = []
        for scope, applicable, row in (
            ("deployment", session and fresh.is_app_admin, deployment),
            ("organization", session and fresh.has(Perm.ORG_SETTINGS), organization),
        ):
            scopes.append(
                OnboardingScopeRead(
                    scope=scope,
                    applicable=applicable,
                    completed=applicable
                    and row is not None
                    and row.onboarding_completed_at is not None,
                    completed_at=row.onboarding_completed_at
                    if applicable and row is not None
                    else None,
                    current_step=row.onboarding_current_step
                    if applicable and row is not None and row.onboarding_completed_at is None
                    else None,
                    updated_at=row.onboarding_updated_at
                    if applicable and row is not None
                    else None,
                )
            )
        scopes.append(
            OnboardingScopeRead(
                scope="personal",
                applicable=True,
                completed=personal_completed_at is not None,
                completed_at=personal_completed_at,
                current_step=None
                if personal_completed_at is not None
                else member.onboarding_current_step,
                updated_at=member.onboarding_updated_at,
            )
        )
        return scopes

    async def update_scope(
        self, ctx: AuthContext, scope: OnboardingScope, data: OnboardingScopeUpdate
    ) -> OnboardingRead:
        """Finish or visit an authorized scope; no configuration or provider call is implied.

        Deployment completion is shared installation-wide, organization completion
        is shared within the selected tenant, and personal completion stays per member.
        Shared writes are serialized and an already completed scope cannot be reopened.
        """
        if scope == "personal":
            return await self.update(
                ctx, OnboardingUpdate.model_validate(data.model_dump(exclude_unset=True))
            )
        member = await self._member(ctx)
        person = await user_repo.get_by_id(self.db, member.user_id)
        fresh = self._scope_context(ctx, member, person)
        if not self._session_scope(ctx) or person is None or not person.is_active:
            raise AuthorizationError(
                message="Shared setup progress requires a personal signed-in account", details={}
            )
        if scope == "deployment":
            if not fresh.is_app_admin:
                raise AuthorizationError(
                    message="Deployment setup requires app administrator access", details={}
                )
            if data.current_step is not None and data.current_step != "admin.deployment":
                raise BadRequestError(
                    message="This screen does not belong to deployment setup", details={}
                )
            row: DeploymentSettings | Organization = await onboarding_repo.deployment_for_update(
                self.db
            )
        else:
            if not fresh.has(Perm.ORG_SETTINGS):
                raise AuthorizationError(
                    message="Organization setup requires org:settings", details={}
                )
            if data.current_step is not None and data.current_step not in get_args(
                OrganizationOnboardingStep
            ):
                raise BadRequestError(
                    message="This screen does not belong to organization setup", details={}
                )
            organization = await onboarding_repo.organization_for_update(
                self.db, ctx.organization_id
            )
            if organization is None:
                raise NotFoundError(message="Organization not found", details={})
            row = organization
        identity = await onboarding_repo.shared_identity(
            self.db, organization_id=ctx.organization_id, user_id=member.user_id
        )
        if identity is None:
            raise NotFoundError(message="Organization membership not found", details={})
        current_member, current_person = identity
        current = self._scope_context(ctx, current_member, current_person)
        if not current_person.is_active or (
            not current.is_app_admin
            if scope == "deployment"
            else not current.has(Perm.ORG_SETTINGS)
        ):
            raise AuthorizationError(
                message="Shared setup authority changed; reload before continuing", details={}
            )
        await onboarding_repo.save_shared(self.db, row=row, data=data)
        return await self.state(ctx)

    async def _setup_agent(self, ctx: AuthContext) -> OnboardingAgent | None:
        try:
            agent = await ShippedAgentService(self.db).setup_candidate(ctx, None)
        except AuthorizationError, NotFoundError:
            # An inaccessible draft must not become an invitation to bypass its grants.
            return None
        return OnboardingAgent(id=agent.id, name=agent.name) if agent is not None else None

    async def _agents(self, ctx: AuthContext) -> list[OnboardingAgent]:
        agents: list[OnboardingAgent] = []
        skip = 0
        # The registry applies effective resource grants, not just role names.
        while True:
            page, total = await self.registry.list_agents(ctx, skip=skip, limit=100)
            agents.extend(
                OnboardingAgent(id=agent.id, name=agent.name)
                for agent in page
                if agent.can_run and agent.status == AgentStatus.PUBLISHED.value
            )
            skip += len(page)
            if not page or skip >= total:
                break
        return agents

    async def preview_member(self, ctx: AuthContext, user_id: UUID) -> MemberStartRead:
        """Check a current teammate without impersonation or disclosing their private resources."""
        await self._member(ctx)
        if not ctx.has(Perm.MEMBERS_MANAGE):
            raise AuthorizationError(
                message="Only a member manager can preview team readiness", details={}
            )
        target = await member_repo.get_active(
            self.db, organization_id=ctx.organization_id, user_id=user_id
        )
        if target is None:
            raise NotFoundError(message="Member not found", details={})
        user = await user_repo.get_by_id(self.db, user_id)
        if user is None:
            raise NotFoundError(message="Member not found", details={})
        member_ctx = AuthContext(
            user_id=user_id,
            organization_id=ctx.organization_id,
            role=target.role,
            is_app_admin=user.is_app_admin,
        )
        mine = {agent.id for agent in await self._agents(ctx)}
        theirs = {agent.id for agent in await self._agents(member_ctx)}
        return MemberStartRead(has_common_agent=bool(mine & theirs))

    async def update(self, ctx: AuthContext, data: OnboardingUpdate) -> OnboardingRead:
        member = await self._member(ctx, for_update=True)
        await onboarding_repo.save(self.db, member=member, data=data)
        return await self.state(ctx)

    async def prepare(self, ctx: AuthContext, model_profile_id: UUID) -> OnboardingAgent:
        """Explicitly create one text-only starter; repeated requests never edit an existing agent.

        The caller chooses the shared model. Publication reuses all normal model,
        budget and scope validation; no provider call, sandbox or integration is needed.
        """
        await self._member(ctx)
        if not ctx.has(Perm.AGENTS_EDIT) or not ctx.has(Perm.AGENTS_PUBLISH):
            raise AuthorizationError(
                message="You cannot prepare an agent for this organization", details={}
            )
        profiles = await ModelProfileService(self.db).list_profiles(ctx)
        by_id = {profile.id: profile for profile in profiles}
        profile = by_id.get(model_profile_id)
        if profile is None or not choosable_for_others(profile, by_id):
            raise BadRequestError(
                message="Choose a shared chat model for the starter",
                details={"model_profile_id": model_profile_id},
            )
        # Use the install advisory lock: FOR UPDATE on the organization would
        # invert the registry's ceiling lock -> organization FK lock order.
        await organization_assistant_repo.lock_for_install(self.db, ctx.organization_id)
        if await organization_repo.get_by_id(self.db, ctx.organization_id) is None:
            raise NotFoundError(message="Organization not found", details={})
        existing = await agent_repo.get_by_slug(
            self.db, STARTER_SLUG, organization_id=ctx.organization_id
        )
        if existing is not None:
            agent, spec, _version = await self.registry.get_runnable_spec(ctx, existing.id)
            if spec.model_profile_id != model_profile_id:
                raise BadRequestError(
                    message="The existing starter uses another model. Change it in the Builder; its draft was kept.",
                    details={"agent_id": agent.id},
                )
            return OnboardingAgent(id=agent.id, name=agent.name)
        spec = AgentSpec(
            name=STARTER_NAME,
            description="Try a meeting plan, a document question or an offer comparison using fictional examples.",
            instructions=(
                "Help the person complete the task using the material in their message. "
                "Answer in their language. Distinguish provided facts from assumptions, "
                "and say when the material cannot answer a question. Do not claim to have "
                "read files, used integrations or performed actions outside this conversation. "
                "Use clear headings, practical next actions and tables when useful."
            ),
            model_profile_id=model_profile_id,
            budget=BudgetSpec(monthly_usd=5),
        )
        agent = await self.registry.create(ctx, spec, visibility=Visibility.ORG, choose_model=False)
        await self.registry.publish(ctx, agent.id, note="Prepare first task")
        return OnboardingAgent(id=agent.id, name=agent.name)
