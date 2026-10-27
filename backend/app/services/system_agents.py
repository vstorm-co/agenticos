"""Seed the platform's system agents into an organization, and find them again.

The definitions are in `app.agents.system_agents`; this module turns one into an
agent row. A new organization gets every definition when it is created. One
created before a definition existed gets it the first time something needs it,
through :meth:`SystemAgentService.ensure` - there is no start-up sweep over every
organization, and a read never seeds.

A seeded agent publishes straight away when the organization already has a model
profile, on the oldest one, so the choice is the same whichever request seeds it.
Without a profile it stays a draft, as any agent without a model does: a person
picks the model and publishes it, and until then the features that use it say so.

An organization may also create more agents of a definition's kind - a judge of
a dataset's own (:meth:`SystemAgentService.create_judge`), or one from New agent
(:meth:`SystemAgentService.create_from_console`). Each starts from the
definition's budget, publishes the same way, and is isolated like the seeded one;
only the seeded one carries the key.
"""

import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, BudgetSpec, ModelSettingsSpec
from app.agents.system_agents import JUDGE, SYSTEM_AGENTS, SystemAgentDef, system_agent
from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    BadRequestError,
    NotFoundError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent, AgentKind
from app.db.models.resource_grant import Visibility
from app.repositories import agent_repo, credential_repo, member_repo
from app.schemas.agent import SystemAgentCreate
from app.services.access import AGENT, resolve_access
from app.services.agent_registry import AgentRegistryService
from app.services.grading_model import grading_profile

logger = logging.getLogger(__name__)


def _seed_spec(definition: SystemAgentDef, *, model_profile_id: UUID | None) -> AgentSpec:
    """The spec a system agent is seeded with, on `model_profile_id` when there is one."""
    return AgentSpec(
        name=definition.name,
        description=definition.description,
        instructions=definition.instructions,
        model_profile_id=model_profile_id,
        model_settings=ModelSettingsSpec(temperature=definition.temperature),
        budget=BudgetSpec(monthly_usd=definition.monthly_usd),
    )


class SystemAgentService:
    """Seed and look up an organization's system agents."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)

    async def seed(self, *, organization_id: UUID, owner_id: UUID) -> None:
        """Create every system agent in a brand-new organization.

        Seeded as the owner, the shape `_seed_bundled_skills` uses. One that cannot
        be created - the deployment's agent ceiling, a taken name - is logged and
        left for :meth:`ensure`, so it never refuses the organization itself.
        """
        for definition in SYSTEM_AGENTS:
            try:
                await self._create(definition, organization_id=organization_id, owner_id=owner_id)
            except AlreadyExistsError, BadRequestError:
                logger.warning(
                    "System agent %r was not seeded into organization %s",
                    definition.key,
                    organization_id,
                    exc_info=True,
                )

    async def ensure(self, *, organization_id: UUID, key: str) -> Agent:
        """The organization's system agent `key`, seeding it when it has none.

        Only for paths that are about to use it: seeding writes an agent and an
        audit entry, which a read must not.

        Raises:
            SystemAgentUnavailableError: `not_seeded` - the organization has no owner
                to attribute it to, or it cannot be created (the deployment's agent
                ceiling, or both its names taken by other agents).
        """
        existing = await agent_repo.get_system(self.db, organization_id=organization_id, key=key)
        if existing is not None:
            await self._adopt(existing, system_agent(key), organization_id=organization_id)
            return existing
        definition = system_agent(key)
        owner_id = await member_repo.first_owner_id(self.db, organization_id=organization_id)
        if owner_id is None:
            raise SystemAgentUnavailableError(
                message=f"'{definition.name}' could not be set up: the organization has no owner",
                key=key,
                reason="not_seeded",
            )
        try:
            return await self._create(
                definition, organization_id=organization_id, owner_id=owner_id
            )
        except (AlreadyExistsError, BadRequestError) as exc:
            raise SystemAgentUnavailableError(
                message=f"'{definition.name}' could not be set up: {exc.message}",
                key=key,
                reason="not_seeded",
            ) from exc

    async def adopt_model(self, *, organization_id: UUID) -> None:
        """Publish the system agents still waiting for a model on the organization's first.

        An organization is seeded before it has a model, so its system agents
        start as drafts with none. Called once it has one, so the judge works
        without anybody having to find it and publish it first.
        """
        for definition in SYSTEM_AGENTS:
            agent = await agent_repo.get_system(
                self.db, organization_id=organization_id, key=definition.key
            )
            if agent is not None:
                await self._adopt(agent, definition, organization_id=organization_id)

    async def _adopt(
        self, agent: Agent, definition: SystemAgentDef, *, organization_id: UUID
    ) -> None:
        """Publish a seeded agent nobody has touched on the oldest model, and audit it.

        Untouched is exact: never published, and its draft still the spec it was
        seeded with, no model included. A draft somebody edited in any way is
        theirs to publish, and an organization with no model or no owner to act
        as leaves it waiting.
        """
        if agent.current_version_id is not None:
            return
        drafted = AgentSpec.model_validate(agent.draft_spec)
        seeded = _seed_spec(definition, model_profile_id=None)
        if drafted.model_dump() != seeded.model_copy(update={"name": drafted.name}).model_dump():
            return
        profile = await credential_repo.oldest_profile(self.db, organization_id=organization_id)
        owner_id = await member_repo.first_owner_id(self.db, organization_id=organization_id)
        if profile is None or owner_id is None:
            return
        ctx = AuthContext(user_id=owner_id, organization_id=organization_id, role=OrgRoleName.OWNER)
        await self.registry.save_draft(
            ctx, agent.id, drafted.model_copy(update={"model_profile_id": profile.id})
        )
        await self._publish(ctx, agent, published=True, note="Seeded")
        if agent.current_version_id is not None:
            await record_audit(
                self.db,
                actor_user_id=None,
                organization_id=organization_id,
                action="system_agent.published",
                target_type="agent",
                target_id=str(agent.id),
                details={
                    "key": definition.key,
                    "model_profile_id": str(profile.id),
                    "model": profile.label,
                },
            )

    async def _create(
        self, definition: SystemAgentDef, *, organization_id: UUID, owner_id: UUID
    ) -> Agent:
        """Create, mark and - when a model is available - publish one system agent.

        A concurrent request seeding the same agent loses on the unique key and
        reads the winner's row. A person's own agent holding the name is not
        taken over: the seed retries once under a suffixed name.
        """
        ctx = AuthContext(user_id=owner_id, organization_id=organization_id, role=OrgRoleName.OWNER)
        profile = await credential_repo.oldest_profile(self.db, organization_id=organization_id)
        spec = _seed_spec(definition, model_profile_id=None if profile is None else profile.id)
        try:
            agent = await self._insert(ctx, spec, definition=definition)
        except IntegrityError:
            winner = await agent_repo.get_system(
                self.db, organization_id=organization_id, key=definition.key
            )
            if winner is None:
                raise
            return winner
        return await self._publish(ctx, agent, published=profile is not None, note="Seeded")

    async def create_judge(
        self,
        ctx: AuthContext,
        *,
        name: str,
        description: str,
        instructions: str,
        visibility: Visibility,
        model_profile_id: UUID | None = None,
    ) -> Agent:
        """A judge of the organization's own, created by the caller from the judge definition.

        As :meth:`create_of_kind` creates one, with the prompt and description of
        the dataset it grades.

        Raises:
            AlreadyExistsError: Another agent of the organization holds the name.
            NotFoundError: `model_profile_id` is not one of the organization's models.
        """
        return await self.create_of_kind(
            ctx,
            JUDGE,
            name=name,
            visibility=visibility,
            model_profile_id=model_profile_id,
            description=description,
            instructions=instructions,
        )

    async def create_of_kind(
        self,
        ctx: AuthContext,
        definition: SystemAgentDef,
        *,
        name: str,
        visibility: Visibility,
        model_profile_id: UUID | None = None,
        description: str | None = None,
        instructions: str | None = None,
    ) -> Agent:
        """An agent of `definition`'s kind, created by the caller from the definition.

        It runs on `model_profile_id`, or on the organization's oldest model, at
        the definition's temperature and budget, with its description and
        instructions unless others are given, and is as widely visible as
        `visibility`. It publishes straight away when it has a model and the
        caller may publish it - a draft otherwise, like a seeded one, for an
        administrator to publish, since every later change to a system agent
        takes `org:settings`. It never carries the definition's key: the seeded one
        stays the organization's default. The caller has already been allowed to
        create agents.

        Raises:
            AlreadyExistsError: Another agent of the organization holds the name.
            NotFoundError: `model_profile_id` is not one of the organization's models.
        """
        if model_profile_id is None:
            grading = (
                await grading_profile(self.db, organization_id=ctx.organization_id, graded=[])
                if definition.kind == AgentKind.JUDGE
                else None
            )
            oldest = grading or await credential_repo.oldest_profile(
                self.db, organization_id=ctx.organization_id
            )
            model_profile_id = None if oldest is None else oldest.id
        elif (
            await credential_repo.get_profile(
                self.db, model_profile_id, organization_id=ctx.organization_id
            )
            is None
        ):
            raise NotFoundError(
                message="This organization has no such model",
                details={"model_profile_id": model_profile_id},
            )
        spec = AgentSpec(
            name=name,
            description=definition.description if description is None else description,
            instructions=definition.instructions if instructions is None else instructions,
            model_profile_id=model_profile_id,
            model_settings=ModelSettingsSpec(temperature=definition.temperature),
            budget=BudgetSpec(monthly_usd=definition.monthly_usd),
        )
        agent = await self.registry.create(ctx, spec, visibility=visibility)
        publishes = model_profile_id is not None and await resolve_access(
            self.db, ctx, agent, Perm.AGENTS_PUBLISH, resource_type=AGENT
        )
        # Published before it takes its kind, which puts changes behind org:settings:
        # making one is its creator's, and a dataset's judge left a draft grades nothing.
        agent = await self._publish(ctx, agent, published=publishes, note="Created")
        return await agent_repo.update(
            self.db, agent=agent, update_data={"kind": definition.kind.value}
        )

    async def create_from_console(self, ctx: AuthContext, data: SystemAgentCreate) -> Agent:
        """A system agent the caller picked in New agent.

        Judges, case generators, knowledge helpers and improvers are selected
        where they run; every supported kind can have an organization-owned copy.

        Raises:
            AlreadyExistsError, NotFoundError: As :meth:`create_of_kind` does.
        """
        definition = next(d for d in SYSTEM_AGENTS if d.kind.value == data.kind)
        return await self.create_of_kind(
            ctx,
            definition,
            name=data.name,
            visibility=data.visibility,
            model_profile_id=data.model_profile_id,
        )

    async def _publish(
        self, ctx: AuthContext, agent: Agent, *, published: bool, note: str
    ) -> Agent:
        """Publish an agent created with a model; one that cannot publish stays a draft."""
        if published:
            try:
                await self.registry.publish(ctx, agent.id, note=note)
            except BadRequestError:
                logger.warning(
                    "Agent %s of kind %r stays a draft in organization %s",
                    agent.id,
                    agent.kind,
                    ctx.organization_id,
                    exc_info=True,
                )
            await self.db.refresh(agent)
        return agent

    async def _insert(
        self, ctx: AuthContext, spec: AgentSpec, *, definition: SystemAgentDef
    ) -> Agent:
        try:
            return await self._insert_as(ctx, spec, definition=definition)
        except AlreadyExistsError:
            renamed = spec.model_copy(update={"name": f"{spec.name} (system)"})
            return await self._insert_as(ctx, renamed, definition=definition)

    async def _insert_as(
        self, ctx: AuthContext, spec: AgentSpec, *, definition: SystemAgentDef
    ) -> Agent:
        async with self.db.begin_nested():
            agent = await self.registry.create(ctx, spec, visibility=Visibility.ORG)
            return await agent_repo.update(
                self.db,
                agent=agent,
                update_data={"system_key": definition.key, "kind": definition.kind.value},
            )
