"""One start contract for web, invitations and native clients; never calls a model."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, BudgetSpec
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import AgentStatus
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import Visibility
from app.repositories import (
    agent_repo,
    member_repo,
    onboarding_repo,
    organization_assistant_repo,
    organization_repo,
    user_repo,
)
from app.schemas.onboarding import (
    MemberStartRead,
    OnboardingAgent,
    OnboardingRead,
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
        completed = member.onboarding_completed_at is not None or (
            person is not None
            and person.onboarding_completed_at is not None
            and member.joined_at <= person.onboarding_completed_at
        )
        snoozed_until = (
            member.onboarding_dismissed_at + timedelta(days=1)
            if member.onboarding_dismissed_at is not None
            else None
        )
        if completed or (snoozed_until is not None and snoozed_until <= datetime.now(UTC)):
            snoozed_until = None
        return OnboardingRead(
            organization_id=org.id,
            organization_name=org.name,
            goal=member.onboarding_goal,
            dismissed=completed or snoozed_until is not None,
            completed=completed,
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
