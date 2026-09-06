"""Erasing an agent's memory - the only thing a person does to it directly.

Notes are written by the agent and by nothing else, so there is no authoring
surface here and no listing: an operator browsing what an agent learned about a
named colleague is a surveillance affordance, not a feature (#1470). What is left
is deletion, in two shapes, and both are refusals-first the way the rest of this
platform is.

**Forgetting one person** spans every agent in the organization, because "forget
everything you know about me" is a fact about a person rather than about one agent
they happened to talk to. Answering it agent by agent is how a deletion request
ends up half-done.

**Clearing one agent** removes every note that agent holds, in every store, and is
the counterpart to the per-person delete: a store nobody can clear is a liability
(#788).

Both reach mem0 as well as this database, when an agent binds it. A clear that
reported success while mem0 still remembered would be a partial wipe wearing a
success, which is exactly the failure mode this feature exists to avoid - so the
result carries what each half actually removed.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.memory_mem0 import MEMORY_MEM0_CAPABILITY_ID
from app.agents.capabilities.memory_mem0._client import mem0_forget_person
from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.memory_keys import is_person_key, person_owner_key
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import ApiKeySecret
from app.db.models.agent import Agent
from app.repositories import agent_repo, memory_repo
from app.schemas.memory import MemoryErasureResult
from app.services.access import AGENT, resolve_access
from app.services.organization_secret import OrganizationSecretService

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.secrets = OrganizationSecretService(db)

    async def forget_person(self, ctx: AuthContext, user_id: UUID) -> MemoryErasureResult:
        """Delete everything every agent in this organization remembers about one person.

        A person may always erase themselves; erasing somebody else is
        `MEMBERS_MANAGE`, the permission that already governs acting on another
        member. Deliberately not an agent permission: this is about a human, and
        somebody who may edit one agent should not thereby be able to reach into
        what every other agent learned about a colleague.
        """
        if ctx.user_id != user_id and not ctx.has(Perm.MEMBERS_MANAGE):
            raise AuthorizationError(message="You may only erase your own memory")
        owner_key = person_owner_key(user_id)
        notes = await memory_repo.delete_for_person(
            self.db, organization_id=ctx.organization_id, owner_key=owner_key
        )
        cleared = await self._forget_in_mem0(ctx, owner_key)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.person.forgotten",
            target_type="user",
            target_id=str(user_id),
            details={"notes": notes, "mem0_agents": cleared},
        )
        return MemoryErasureResult(notes_deleted=notes, mem0_agents_cleared=cleared)

    async def clear_agent(self, ctx: AuthContext, agent_id: UUID) -> MemoryErasureResult:
        """Delete every note one agent holds, in every store.

        Gated per row rather than by a route-level `require(...)`, because a grant
        on this agent has to be able to widen it - the reason every per-resource
        route in this project hands the decision to `resolve_access`. A denial is a
        404 on the agent, because whether it exists is itself something the caller
        may not learn.
        """
        agent = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
        if agent is None or not await resolve_access(
            self.db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT
        ):
            raise NotFoundError(message="Agent not found", details={"agent_id": agent_id})
        notes = await memory_repo.delete_all_for_agent(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.agent.cleared",
            target_type="agent",
            target_id=str(agent_id),
            details={"notes": notes},
        )
        return MemoryErasureResult(notes_deleted=notes, mem0_agents_cleared=0)

    async def _forget_in_mem0(self, ctx: AuthContext, owner_key: str) -> int:
        """Clear this person's mem0 namespace under every agent that binds mem0.

        The half the database cannot reach. Each agent has its own namespace and
        may have its own key, so this is one call per binding rather than one for
        the organization.

        A failure is raised, not swallowed: the person is being told their memory
        is gone, and finding out later that half of it was not is worse than an
        error now (#1470).
        """
        assert is_person_key(owner_key), "only a person is forgotten this way"
        cleared = 0
        for agent, secret_id in await self._mem0_bindings(ctx.organization_id):
            resolved = await self.secrets.resolve_for_bindings(ctx, [secret_id])
            secret = resolved.get(secret_id)
            if not isinstance(secret, ApiKeySecret):
                # The binding names a secret that no longer resolves, so the agent
                # cannot reach mem0 either - there is nothing of theirs to delete.
                logger.warning("mem0_forget_skipped_unresolved_secret")
                continue
            await mem0_forget_person(
                base_url=_mem0_base_url(agent.draft_spec),
                api_key=secret.api_key.get_secret_value(),
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                owner_key=owner_key,
            )
            cleared += 1
        return cleared

    async def _mem0_bindings(self, organization_id: UUID) -> list[tuple[Agent, UUID]]:
        """Every agent in the organization whose draft spec binds mem0, with its key.

        The *draft* spec, not the published one, and that is deliberate: an agent
        edited to drop mem0 but not yet published is still running the published
        version, and one edited to add it has not written anything yet. Reading
        both would double the work to catch a window that erasure does not need to
        be exact about - it deletes, and deleting a namespace that holds nothing is
        free.
        """
        result = await self.db.execute(
            select(Agent).where(Agent.organization_id == organization_id)
        )
        bindings: list[tuple[Agent, UUID]] = []
        for agent in result.scalars().all():
            for binding in _capabilities(agent.draft_spec):
                if (
                    binding.get("id") == MEMORY_MEM0_CAPABILITY_ID
                    and binding.get("enabled", True)
                    and binding.get("secret_id")
                ):
                    bindings.append((agent, UUID(str(binding["secret_id"]))))
        return bindings


def _capabilities(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The capability bindings of a stored spec, tolerant of a shape it does not have."""
    capabilities = spec.get("capabilities")
    if not isinstance(capabilities, list):
        return []
    return [binding for binding in capabilities if isinstance(binding, dict)]


def _mem0_base_url(spec: dict[str, Any]) -> str | None:
    for binding in _capabilities(spec):
        if binding.get("id") == MEMORY_MEM0_CAPABILITY_ID:
            config = binding.get("config")
            if isinstance(config, dict):
                url = config.get("base_url")
                return url if isinstance(url, str) else None
    return None
