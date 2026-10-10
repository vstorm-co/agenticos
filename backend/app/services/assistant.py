"""Each organization's AI Architect: always there, ready to talk (#2063).

Nobody has to install it. The first time anybody in an organization opens the
console, the widget asks for the assistant and it is installed: an ordinary agent
from the *AI Architect* template, shared with the whole organization, bound to
the platform's own MCP server, and published on the organization's first model.
An organization with no model yet gets it as a draft, and the widget says so - an
administrator connects a model, and the next look publishes it.

It is installed as the organization's owner, because the person who happens to
open the console first may not be allowed to create agents. Who may talk to it is
`agents:run`, as for any agent; what it does is done as whoever is talking to it,
through the platform's MCP server with a credential minted for them.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, BudgetSpec
from app.core.exceptions import AppException, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent
from app.db.models.organization_assistant import OrganizationAssistant
from app.db.models.resource_grant import Visibility
from app.repositories import (
    agent_repo,
    credential_repo,
    member_repo,
    organization_assistant_repo,
)
from app.schemas.assistant import AssistantRead, AssistantUpdate
from app.services import agent_templates
from app.services.agent_registry import AgentRegistryService, slugify

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "general/platform-assistant"
"""The shipped template every organization's assistant is installed from."""


class AssistantService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)

    async def state(self, ctx: AuthContext) -> AssistantRead:
        """The organization's assistant as the widget needs it, installing it first.

        Never refuses a member: an assistant that cannot be installed - the
        organization is at its agent ceiling - is reported as `unavailable`, so
        the widget can say so rather than every page load erroring.
        """
        can_configure = ctx.has(Perm.ORG_SETTINGS)
        can_use = ctx.has(Perm.AGENTS_RUN)
        try:
            row, agent = await self._installed(ctx.organization_id)
        except AppException:
            logger.exception("Could not install the assistant in %s", ctx.organization_id)
            return AssistantRead(
                status="unavailable",
                agent_id=None,
                name=_template().name,
                greeting=None,
                can_use=can_use,
                can_configure=can_configure,
            )
        if row.enabled and agent.current_version_id is None:
            agent = await self._publish_when_possible(ctx.organization_id, agent)
        return self._read(row, agent, can_use=can_use, can_configure=can_configure)

    async def update(self, ctx: AuthContext, data: AssistantUpdate) -> AssistantRead:
        """Change how the assistant greets people, what it is called, what it runs
        on and what company knowledge it has - or switch it off.

        The agent-shaped settings are written to its draft and published, as the
        administrator making the change, so the version history says who did it.
        """
        row, agent = await self._installed(ctx.organization_id)
        own = data.model_dump(include={"enabled", "greeting"}, exclude_unset=True)
        if own:
            row = await organization_assistant_repo.update(self.db, row=row, update_data=own)
        spec_changes = data.model_dump(
            include={"name", "model_profile_id", "collection_ids"}, exclude_unset=True
        )
        if spec_changes:
            spec = AgentSpec.model_validate(agent.draft_spec).model_copy(update=spec_changes)
            agent = await self.registry.save_draft(ctx, agent.id, spec)
            if spec.model_profile_id is not None:
                await self.registry.publish(ctx, agent.id, note="Assistant settings")
                agent = await self.registry.get(ctx, agent.id)
        return self._read(row, agent, can_use=ctx.has(Perm.AGENTS_RUN), can_configure=True)

    async def _installed(self, organization_id: UUID) -> tuple[OrganizationAssistant, Agent]:
        """The assistant's row and agent, installing both if this is the first look."""
        row = await organization_assistant_repo.get(self.db, organization_id)
        if row is None:
            await organization_assistant_repo.lock_for_install(self.db, organization_id)
            row = await organization_assistant_repo.get(self.db, organization_id)
        if row is None:
            agent = await self._install(organization_id)
            row = await organization_assistant_repo.create(
                self.db, organization_id=organization_id, agent_id=agent.id
            )
            return row, agent
        agent = await agent_repo.get(self.db, row.agent_id, organization_id=organization_id)
        if agent is None:  # pragma: no cover - the row cascades with its agent
            raise NotFoundError(message="The assistant's agent is gone")
        return row, agent

    async def _install(self, organization_id: UUID) -> Agent:
        template = _template()
        installer = await self._installer(organization_id)
        name = template.name
        if await agent_repo.get_by_slug(self.db, slugify(name), organization_id=organization_id):
            # Somebody already has an agent by that name; the assistant takes the
            # next free one rather than failing to exist.
            name = f"{template.name} (AgenticOS)"
        spec = AgentSpec(
            name=name,
            description=template.description,
            instructions=template.instructions,
            capabilities=list(template.capabilities),
            mcp_servers=list(template.mcp_servers),
            budget=(
                BudgetSpec(monthly_usd=template.budget_usd)
                if template.budget_usd is not None
                else None
            ),
        )
        return await self.registry.create(installer, spec, visibility=Visibility.ORG)

    async def _publish_when_possible(self, organization_id: UUID, agent: Agent) -> Agent:
        """Publish the draft on the organization's first model, once it has one."""
        profiles = await credential_repo.list_profiles(self.db, organization_id=organization_id)
        if not profiles:
            return agent
        installer = await self._installer(organization_id)
        spec = AgentSpec.model_validate(agent.draft_spec)
        if spec.model_profile_id is None:
            spec = spec.model_copy(update={"model_profile_id": profiles[0].id})
            agent = await self.registry.save_draft(installer, agent.id, spec)
        await self.registry.publish(installer, agent.id, note="Installed")
        return await self.registry.get(installer, agent.id)

    async def _installer(self, organization_id: UUID) -> AuthContext:
        """The organization's owner, whom the assistant is installed and published as."""
        owner_id = await member_repo.first_owner_id(self.db, organization_id=organization_id)
        if owner_id is None:  # pragma: no cover - every organization has an owner
            raise NotFoundError(message="This organization has no owner")
        return AuthContext(
            user_id=owner_id, organization_id=organization_id, role=OrgRoleName.OWNER
        )

    @staticmethod
    def _read(
        row: OrganizationAssistant, agent: Agent, *, can_use: bool, can_configure: bool
    ) -> AssistantRead:
        spec = AgentSpec.model_validate(agent.draft_spec)
        status = (
            "disabled"
            if not row.enabled
            else "ready"
            if agent.current_version_id is not None
            else "needs_model"
        )
        return AssistantRead(
            status=status,
            agent_id=agent.id,
            slug=agent.slug,
            name=agent.name,
            greeting=row.greeting,
            avatar_url=agent.avatar_url,
            avatar_color=agent.avatar_color,
            model_profile_id=spec.model_profile_id,
            collection_ids=list(spec.collection_ids),
            can_use=can_use,
            can_configure=can_configure,
        )


def _template() -> agent_templates.AgentTemplate:
    template = agent_templates.get(TEMPLATE_KEY)
    if template is None:  # pragma: no cover - the template ships with the image
        raise NotFoundError(message="The assistant template is missing from this deployment")
    return template
