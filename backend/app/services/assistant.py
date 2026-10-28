"""Each organization's AI Architect: always there, ready to talk (#2063).

Nobody has to install it. The first time anybody in an organization opens the
console, the widget asks for the assistant and it is installed: an ordinary agent
from the *Architect* template, shared with the whole organization, bound to
the platform's own MCP server, and published on the organization's first model.
An organization with no model yet gets it as a draft, and the widget says so - an
administrator connects a model, and the next look publishes it.

It is installed as the organization's owner, because the person who happens to
open the console first may not be allowed to create agents. Who may talk to it is
`agents:run`, as for any agent; what it does is done as whoever is talking to it,
through the platform's MCP server with a credential minted for them.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, BudgetSpec
from app.core.exceptions import AppException, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent
from app.db.models.agent_run import RunStatus
from app.db.models.organization_assistant import OrganizationAssistant
from app.db.models.resource_grant import Visibility
from app.db.updates import writable
from app.repositories import (
    agent_repo,
    agent_run_repo,
    credential_repo,
    member_repo,
    organization_assistant_repo,
)
from app.repositories.agent_run import RunFilters
from app.schemas.assistant import AssistantRead, AssistantSignals, AssistantUpdate
from app.services import agent_templates
from app.services.agent_registry import AgentRegistryService, slugify
from app.services.model_profile import usable_for_agents
from app.services.sandbox_connection import SandboxConnectionService

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "general/platform-assistant"
# Its mark, worn as an ordinary agent picture so every place an agent's face is
# drawn - the catalog, a picker, the transcript, Slack - draws the Architect's.
AVATAR = agent_templates.TEMPLATES_ROOT / TEMPLATE_KEY / "avatar.png"
"""The shipped template every organization's assistant is installed from."""
RECENT_FAILURE = timedelta(days=1)
"""How far back a failed run is still worth the bubble raising."""


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
            # A savepoint, so a failed first install leaves nothing behind: the
            # gallery skills and the sandbox connection it set up before the agent
            # was refused would otherwise commit with the request that reports
            # the assistant unavailable.
            async with self.db.begin_nested():
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

    async def signals(self, ctx: AuthContext) -> AssistantSignals:
        """What the widget's bubble may speak to, read the way each listing reads it.

        One request on every page instead of three listings - every agent, the
        approval queue and the reader's failed runs - fetched to count them (#2248).
        Each is asked through the same scope its own page uses, so the bubble never
        speaks to something its page would not show.
        """
        pending = 0
        if ctx.has(Perm.APPROVALS_DECIDE):
            _rows, pending = await agent_run_repo.list_approvals(
                self.db, organization_id=ctx.organization_id, limit=1
            )
        failed_run_id = None
        if ctx.has(Perm.RUNS_VIEW) and ctx.user_id is not None:
            runs, _total = await agent_run_repo.list_runs(
                self.db,
                organization_id=ctx.organization_id,
                filters=RunFilters(
                    statuses=[RunStatus.FAILED.value],
                    user_id=ctx.user_id,
                    started_from=datetime.now(UTC) - RECENT_FAILURE,
                ),
                limit=1,
            )
            failed_run_id = runs[0].id if runs else None
        return AssistantSignals(
            pending_approvals=pending,
            has_agents=ctx.has(Perm.AGENTS_VIEW) and await self.registry.any_visible(ctx),
            failed_run_id=failed_run_id,
        )

    async def update(self, ctx: AuthContext, data: AssistantUpdate) -> AssistantRead:
        """Change how the assistant greets people, or switch it off.

        Only what the organization decides about it as its assistant. Its name,
        model, knowledge and the rest of its spec are the agent's, edited and
        published in the Builder like any agent's - one place for them, rather
        than a second form here that wrote the same draft.
        """
        row, agent = await self._installed(ctx.organization_id)
        own = writable(data, over=OrganizationAssistant)
        if own:
            row = await organization_assistant_repo.update(self.db, row=row, update_data=own)
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
                self.db,
                organization_id=organization_id,
                agent_id=agent.id,
                mark_path=agent.avatar_url,
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
            name = _fallback_name(template)
        # Its skills - this platform's good practice for building agents (#2069) -
        # installed from the gallery the way a template install installs them.
        skills = await self.registry.template_skills(installer, template)
        capabilities = list(template.capabilities)
        # Files and code - reading a pasted agent, running it - where the
        # deployment has a sandbox to give it. Not in the template: bound there, an
        # organization with none could never publish its assistant (#2069, #2070).
        if await SandboxConnectionService(self.db).ensure_local_connection(organization_id):
            capabilities.append(
                {"id": "sandbox", "config": {"backend": "service", "include_execute": True}}
            )
        spec = AgentSpec(
            name=name,
            description=template.description,
            instructions=template.instructions,
            capabilities=capabilities,
            mcp_servers=list(template.mcp_servers),
            skill_ids=[skill.id for skill in skills],
            budget=(
                BudgetSpec(monthly_usd=template.budget_usd)
                if template.budget_usd is not None
                else None
            ),
            starters=list(template.starters),
        )
        agent = await self.registry.create(installer, spec, visibility=Visibility.ORG)
        return await self.registry.set_avatar(
            installer, agent.id, file_data=AVATAR.read_bytes(), content_type="image/png"
        )

    async def _publish_when_possible(self, organization_id: UUID, agent: Agent) -> Agent:
        """Publish the draft on the organization's first chat model, once it has one.

        A text-to-speech or embedding profile is not one (#2487), and neither is a
        profile whose key was deleted (#2478): publish refuses both, so the
        assistant waits for a model it can run on.
        """
        profiles = [
            profile
            for profile in await credential_repo.list_profiles(
                self.db, organization_id=organization_id
            )
            if usable_for_agents(profile)
        ]
        if not profiles:
            return agent
        installer = await self._installer(organization_id)
        for profile in profiles:
            if not profile.fallback_profile_ids or not await self.registry.model_profile_problems(
                installer, profile.id
            ):
                selected_id = profile.id
                break
        else:
            return agent
        agent = await self.registry.get(installer, agent.id, perm=Perm.AGENTS_EDIT, for_update=True)
        if agent.current_version_id is not None:
            return agent
        spec = AgentSpec.model_validate(agent.draft_spec)
        if spec.model_profile_id is None:
            spec = spec.model_copy(update={"model_profile_id": selected_id})
            agent = await self.registry.save_draft(installer, agent.id, spec)
        elif await self.registry.model_profile_problems(installer, spec.model_profile_id):
            # A deliberately selected model is the author's to replace.
            return agent
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
            named_by_default=agent.name in (_template().name, _fallback_name(_template())),
            greeting=row.greeting,
            avatar_url=agent.avatar_url,
            avatar_color=agent.avatar_color,
            wears_mark=agent.avatar_url is None or agent.avatar_url == row.mark_path,
            can_use=can_use,
            can_configure=can_configure,
        )


def _fallback_name(template: agent_templates.AgentTemplate) -> str:
    """The name it installs under where an agent already took the template's handle."""
    return f"{template.name} (AgenticOS)"


def _template() -> agent_templates.AgentTemplate:
    template = agent_templates.get(TEMPLATE_KEY)
    if template is None:  # pragma: no cover - the template ships with the image
        raise NotFoundError(message="The assistant template is missing from this deployment")
    return template
