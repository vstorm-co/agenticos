"""Install and refresh platform agents without taking ownership of people's edits."""

from dataclasses import replace
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent, AgentStatus
from app.repositories import agent_repo, member_repo, organization_assistant_repo
from app.services import agent_templates, skill_library
from app.services.agent_defaults import (
    ARCHITECT,
    FIELDS,
    STARTER,
    baseline,
    fingerprint,
    legacy_defaults,
    merge_defaults,
    previous_fingerprint,
    template_release,
)
from app.services.agent_registry import AgentRegistryService, slugify
from app.services.sandbox_connection import SandboxConnectionService
from app.services.skills import SkillService


class ShippedAgentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)

    async def setup_candidate(self, ctx: AuthContext, agent_id: UUID | None) -> Agent | None:
        """A setup reply belongs only to the shipped starter or the enabled Architect.

        This grants no draft execution. Ordinary, renamed lookalikes, archived or
        published agents always take the normal publication and run checks.
        """
        agent = await agent_repo.get_shipped_starter(self.db, organization_id=ctx.organization_id)
        # An explicit Architect selection is authenticated by the organization row,
        # never by its display name or a client-supplied template marker.
        if agent_id is not None and (agent is None or agent.id != agent_id):
            assistant = await organization_assistant_repo.get(self.db, ctx.organization_id)
            if assistant is None or not assistant.enabled or assistant.agent_id != agent_id:
                return None
            agent = await self.registry.get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        if (
            agent is None
            or (agent_id is not None and agent.id != agent_id)
            or agent.status != AgentStatus.DRAFT.value
            or agent.current_version_id is not None
        ):
            return None
        return await self.registry.get(ctx, agent.id, perm=Perm.AGENTS_RUN)

    async def ensure_skills(self, organization_id: UUID) -> None:
        """Seed deployment-owned know-how without borrowing the current member's rights."""
        await organization_assistant_repo.lock_for_install(self.db, organization_id)
        owner = await member_repo.first_owner_id(self.db, organization_id=organization_id)
        if owner is None:
            raise NotFoundError(message="This organization has no owner")
        await SkillService(self.db).synchronize_library(
            AuthContext(user_id=owner, organization_id=organization_id, role=OrgRoleName.OWNER)
        )

    async def starter(self, ctx: AuthContext) -> Agent:
        """Find the installed starter by provenance, falling back to its legacy slug."""
        agent = await agent_repo.get_shipped_starter(self.db, organization_id=ctx.organization_id)
        if agent is None:
            template = self._template(STARTER)
            agent = await agent_repo.get_by_slug(
                self.db, slugify(template.name), organization_id=ctx.organization_id
            )
            if agent is None:
                installed = await self.registry.install_template(ctx, STARTER)
                agent = await self.registry.get(ctx, installed.agent_id)
        return await self.refresh(ctx, agent, STARTER)

    async def refresh(
        self,
        ctx: AuthContext,
        agent: Agent,
        key: str,
        *,
        legacy_instructions_fingerprint: str | None = None,
    ) -> Agent:
        """Publish refreshed defaults, preserving even unpublished model/settings edits.

        The published spec and draft are merged independently. A publication uses
        only the old published settings; a pending model/budget edit remains a draft.
        The caller owns the organization install lock and a savepoint.
        """
        if agent.organization_id != ctx.organization_id:
            raise NotFoundError(message="Agent not found", details={"agent_id": agent.id})
        if agent.status == AgentStatus.ARCHIVED.value:
            return agent
        template = self._template(key)
        release = template_release(
            key,
            AgentSpec(
                name=template.name,
                capabilities=agent_templates.for_this_deployment(template.capabilities),
            ).model_dump_json(include={"capabilities"}),
        )
        if agent.shipped_template is not None and agent.shipped_template.get("release") == release:
            return agent
        agent = await self.registry.get(ctx, agent.id, perm=Perm.AGENTS_EDIT, for_update=True)
        if agent.shipped_template is not None and agent.shipped_template.get("release") == release:
            return agent
        draft = AgentSpec.model_validate(agent.draft_spec)
        previous = agent.shipped_template
        if previous is None:
            previous = await self._legacy_baseline(
                ctx, draft, key, legacy_instructions_fingerprint=legacy_instructions_fingerprint
            )
            if previous is None:
                return agent
        if previous.get("key") != key:
            return agent
        target = await self._target(ctx, template)
        new_draft = merge_defaults(draft, target, previous)
        new_published: AgentSpec | None = None
        if agent.current_version_id is not None:
            version = await agent_repo.get_version(
                self.db, agent.current_version_id, organization_id=ctx.organization_id
            )
            if version is None:
                raise NotFoundError(message="The shipped agent's published version is missing")
            published = AgentSpec.model_validate(version.spec)
            new_published = merge_defaults(published, target, previous)
            # Editing either side of a field protects it on BOTH sides: do not
            # silently update the live prompt while its replacement is being drafted.
            protected = {
                field
                for field in FIELDS
                if fingerprint(draft, field) != previous_fingerprint(previous, field)
                or fingerprint(published, field) != previous_fingerprint(previous, field)
            }
            new_draft = AgentSpec.model_validate(
                {
                    **new_draft.model_dump(),
                    **{field: draft.model_dump()[field] for field in protected},
                }
            )
            new_published = AgentSpec.model_validate(
                {
                    **new_published.model_dump(),
                    **{field: published.model_dump()[field] for field in protected},
                }
            )
            if new_published != published:
                await self.registry.save_draft(ctx, agent.id, new_published)
                await self.registry.publish(ctx, agent.id, note="Refresh shipped agent defaults")
        if AgentSpec.model_validate(agent.draft_spec) != new_draft:
            await self.registry.save_draft(ctx, agent.id, new_draft)
        delivered = baseline(key, target)
        for field in FIELDS:
            if fingerprint(new_draft, field) != delivered[field] or (
                new_published is not None and fingerprint(new_published, field) != delivered[field]
            ):
                delivered[field] = previous.get(field, "customized")
        return await agent_repo.update(
            self.db,
            agent=agent,
            update_data={"shipped_template": {**delivered, "release": release}},
        )

    async def _target(self, ctx: AuthContext, template: agent_templates.AgentTemplate) -> AgentSpec:
        await self.ensure_skills(ctx.organization_id)
        skills = await self.registry.template_skills(ctx, template)
        for skill_key in template.skills:
            entry = skill_library.gallery_get(skill_key)
            if entry is not None and any(skill.name == entry.name for skill in skills):
                await SkillService(self.db).refresh_gallery(ctx, skill_key)
        capabilities = agent_templates.for_this_deployment(template.capabilities)
        if template.key == ARCHITECT and await SandboxConnectionService(
            self.db
        ).ensure_local_connection(ctx.organization_id):
            capabilities = [binding for binding in capabilities if binding["id"] != "sandbox"]
            capabilities.append(
                {"id": "sandbox", "config": {"backend": "service", "include_execute": True}}
            )
        return AgentSpec(
            name=template.name,
            instructions=template.instructions,
            capabilities=capabilities,
            mcp_servers=list(template.mcp_servers),
            skill_ids=[skill.id for skill in skills],
            starters=list(template.starters),
        )

    async def _legacy_baseline(
        self,
        ctx: AuthContext,
        spec: AgentSpec,
        key: str,
        *,
        legacy_instructions_fingerprint: str | None = None,
    ) -> dict[str, str] | None:
        """Recognize historical shipped values; never trust the AgenticOS name alone.

        The Architect's identity comes from organization_assistants. A legacy
        starter must also have an exact shipped prompt. Unrecognized values stay
        protected instead of being treated as a new baseline we may overwrite.
        """
        history = legacy_defaults()[key]
        if key == STARTER and not any(
            row.recognizes_prompt(fingerprint(spec, "instructions")) for row in history
        ):
            return None
        previous = {"key": key, **dict.fromkeys(FIELDS, "customized")}
        if (
            key == ARCHITECT
            and legacy_instructions_fingerprint is not None
            and fingerprint(spec, "instructions") == legacy_instructions_fingerprint
        ):
            previous["instructions"] = legacy_instructions_fingerprint
        template = self._template(key)
        for row in history:
            if row.recognizes_prompt(fingerprint(spec, "instructions")):
                previous["instructions"] = fingerprint(spec, "instructions")
            # Resolve the historical skill list through the same gallery access
            # checks as an install; no cross-tenant ids enter an agent spec.
            skills = await self.registry.template_skills(
                ctx, replace(template, skills=tuple(row.skills)), install_missing=False
            )
            variants = [
                row.capabilities,
                agent_templates.for_this_deployment(tuple(row.capabilities)),
            ]
            if key == ARCHITECT:
                variants.append(
                    [
                        *[
                            binding
                            for binding in agent_templates.for_this_deployment(
                                tuple(row.capabilities)
                            )
                            if binding["id"] != "sandbox"
                        ],
                        {
                            "id": "sandbox",
                            "config": {"backend": "service", "include_execute": True},
                        },
                    ]
                )
            for capabilities in variants:
                old = AgentSpec(
                    name=spec.name,
                    capabilities=capabilities,
                    mcp_servers=row.mcp_servers,
                    skill_ids=[skill.id for skill in skills],
                    starters=row.starters,
                )
                for field in FIELDS[1:]:
                    if fingerprint(spec, field) == fingerprint(old, field):
                        previous[field] = fingerprint(spec, field)
        return previous

    @staticmethod
    def _template(key: str) -> agent_templates.AgentTemplate:
        template = agent_templates.get(key)
        if template is None:
            raise NotFoundError(
                message="The shipped agent template is missing", details={"key": key}
            )
        return template
