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
a dataset's own (:meth:`SystemAgentService.create_judge`). Each starts from the
definition's budget, publishes the same way, and is isolated like the seeded one;
only the seeded one carries the key.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, BudgetSpec
from app.agents.system_agents import JUDGE, SYSTEM_AGENTS, SystemAgentDef, system_agent
from app.core.exceptions import (
    AlreadyExistsError,
    BadRequestError,
    NotFoundError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentKind
from app.db.models.resource_grant import Visibility
from app.repositories import agent_repo, credential_repo, member_repo
from app.services.agent_registry import AgentRegistryService

logger = logging.getLogger(__name__)


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
            except (AlreadyExistsError, BadRequestError):
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
        spec = AgentSpec(
            name=definition.name,
            description=definition.description,
            instructions=definition.instructions,
            model_profile_id=profile.id if profile is not None else None,
            budget=BudgetSpec(monthly_usd=definition.monthly_usd),
        )
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
        model_profile_id: UUID | None = None,
    ) -> Agent:
        """A judge of the organization's own, created by the caller from the judge definition.

        It runs on `model_profile_id`, or on the organization's oldest model, and
        publishes straight away when it has one - a draft otherwise, like the
        seeded judge. The caller has already been allowed to create agents.

        Raises:
            AlreadyExistsError: Another agent of the organization holds the name.
            NotFoundError: `model_profile_id` is not one of the organization's models.
        """
        if model_profile_id is None:
            oldest = await credential_repo.oldest_profile(
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
            description=description,
            instructions=instructions,
            model_profile_id=model_profile_id,
            budget=BudgetSpec(monthly_usd=JUDGE.monthly_usd),
        )
        agent = await self.registry.create(ctx, spec, visibility=Visibility.ORG)
        agent = await agent_repo.update(
            self.db, agent=agent, update_data={"kind": AgentKind.JUDGE.value}
        )
        return await self._publish(
            ctx, agent, published=model_profile_id is not None, note="Created"
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
