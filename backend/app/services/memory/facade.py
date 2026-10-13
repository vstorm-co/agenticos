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
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.memory_mem0 import MEMORY_MEM0_CAPABILITY_ID
from app.agents.capabilities.memory_mem0._client import mem0_forget_person
from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.memory_keys import INDEX_NAME, is_person_key, person_owner_key
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import ApiKeySecret
from app.db.models.agent import Agent, AgentVersion
from app.db.models.memory import AgentMemoryFile
from app.repositories import agent_repo, memory_repo, organization_repo
from app.schemas.memory import MemoryErasureResult, MemoryNoteList, MemoryNoteRead
from app.services.access import AGENT, resolve_access
from app.services.organization_secret import OrganizationSecretService

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.secrets = OrganizationSecretService(db)

    async def mine(self, ctx: AuthContext, *, skip: int, limit: int) -> MemoryNoteList:
        """What the agents in this organization have written down about the caller.

        No permission, because there is none to ask for: this is the caller's own
        store, and the answer is the same for a Viewer and an Owner. Suppressed
        notes are included - they are the person's, and a view that hid what they
        had suppressed would be one they could not restore anything from.
        """
        return await self._notes_for(
            ctx.organization_id, person_owner_key(ctx.subject_id), skip=skip, limit=limit
        )

    async def for_person(
        self,
        ctx: AuthContext,
        organization_id: UUID,
        user_id: UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        reason: str | None = None,
    ) -> MemoryNoteList:
        """One named person's notes in one named tenant - the deployment admin's view.

        **Not an organization permission, deliberately.** Reading what every agent
        has learned about a named colleague is a surveillance affordance, and the
        earlier answer to that was to expose nothing at all (#1470). What changed
        in #1594 is who may: the person themselves, always, and the deployment's
        own administrator, who already administers accounts across tenants and is
        the party a subject-access request actually reaches. An Owner or Admin of
        the organization is not that party and does not get this by role.

        The read is audited with the actor, the tenant, the subject and the reason
        - and no content, because an audit entry holding what it looked at is a
        second copy of the thing being protected.
        """
        if not ctx.is_app_admin:
            raise AuthorizationError(
                message="Only a deployment administrator may read another person's memory"
            )
        # The tenant is resolved before it is read from. A mistyped or deleted id
        # otherwise answers an empty inventory - indistinguishable from a person
        # with no memory - and records a trail under an organization that never
        # existed, because the audit column carries no foreign key.
        if await organization_repo.get_by_id(self.db, organization_id) is None:
            raise NotFoundError(
                message="Organization not found", details={"organization_id": organization_id}
            )
        notes = await self._notes_for(
            organization_id, person_owner_key(user_id), skip=skip, limit=limit
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=organization_id,
            action="memory.person.inspected",
            target_type="user",
            target_id=str(user_id),
            details={"notes": notes.total, "reason": reason},
        )
        return notes

    async def set_active(self, ctx: AuthContext, file_id: UUID, *, active: bool) -> MemoryNoteRead:
        """Suppress one of the caller's own notes, or restore it.

        The middle answer between living with a note and erasing everything: a
        suppressed note is not listed, not read and not editable by any tool, so
        it stops reaching the model without being destroyed.

        Raises:
            NotFoundError: The note is not in this caller's own store. Not a 403:
                whether a note exists in somebody else's store is itself something
                the caller may not learn.
        """
        row = await self._own_note(ctx, file_id)
        await memory_repo.update(
            self.db,
            file=row,
            update_data={"deactivated_at": None if active else datetime.now(UTC)},
        )
        if not active:
            await self._prune_index(row)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.note.restored" if active else "memory.note.suppressed",
            target_type="memory_file",
            target_id=str(file_id),
            # The note's name, not its content: an entry holding what it
            # suppressed would keep the thing the person suppressed.
            details={"agent_id": str(row.agent_id), "name": row.name},
        )
        names = await self._agent_names({row.agent_id})
        return MemoryNoteRead.model_validate(row).model_copy(
            update={"agent_name": names.get(row.agent_id)}
        )

    async def delete_note(self, ctx: AuthContext, file_id: UUID) -> None:
        """Delete one of the caller's own notes outright."""
        row = await self._own_note(ctx, file_id)
        agent_id, name = row.agent_id, row.name
        await self._prune_index(row)
        await memory_repo.delete(self.db, row)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.note.deleted",
            target_type="memory_file",
            target_id=str(file_id),
            details={"agent_id": str(agent_id), "name": name},
        )

    async def _own_note(self, ctx: AuthContext, file_id: UUID) -> AgentMemoryFile:
        """One note, only if it is in the caller's own store.

        The owner is part of the lookup rather than checked afterwards - owning a
        conversation or being able to edit the agent reaches nothing here, which
        is the separation between personal memory and shared agent knowledge.
        """
        row = await memory_repo.get_owned(
            self.db,
            organization_id=ctx.organization_id,
            owner_key=person_owner_key(ctx.subject_id),
            file_id=file_id,
        )
        if row is None:
            raise NotFoundError(message="Memory note not found", details={"file_id": file_id})
        return row

    async def _notes_for(
        self, organization_id: UUID, owner_key: str, *, skip: int = 0, limit: int = 50
    ) -> MemoryNoteList:
        """One store's page, with the agent names and the stores this cannot reach."""
        rows, total = await memory_repo.list_for_person(
            self.db, organization_id=organization_id, owner_key=owner_key, skip=skip, limit=limit
        )
        names = await self._agent_names({row.agent_id for row in rows})
        items = [
            MemoryNoteRead.model_validate(row).model_copy(
                update={"agent_name": names.get(row.agent_id)}
            )
            for row in rows
        ]
        external = await self._external_stores(organization_id)
        return MemoryNoteList(items=items, total=total, external_stores=external)

    async def _external_stores(self, organization_id: UUID) -> list[str]:
        """Agents whose memories live in a service this listing cannot read.

        The **published** spec where there is one, falling back to the draft for
        an agent that has never been published. Erasure reads the draft
        deliberately - deleting a namespace that holds nothing is free - but a
        disclosure read off the draft says the wrong thing in both directions: an
        agent whose unpublished edit dropped mem0 is still writing there, and one
        that only added it in a draft has written nothing yet (#1594 review).
        """
        rows = await self.db.execute(
            select(Agent, AgentVersion.spec)
            .outerjoin(AgentVersion, Agent.current_version_id == AgentVersion.id)
            .where(Agent.organization_id == organization_id)
        )
        named: set[str] = set()
        for agent, published in rows.all():
            spec = published if isinstance(published, dict) else agent.draft_spec
            if any(
                binding.get("id") == MEMORY_MEM0_CAPABILITY_ID and binding.get("enabled", True)
                for binding in _capabilities(spec)
            ):
                named.add(agent.name)
        return sorted(named)

    async def _prune_index(self, row: AgentMemoryFile) -> None:
        """Drop the suppressed note's line from the store's `MEMORY.md`.

        The index is not an ordinary note: the capability splices it into the
        instructions of every request, so a note stopped by its subject whose
        index line still describes it is a note still reaching the model - part
        of exactly what they asked to stop (#1594 review). Deleting the note
        outright leaves the same stale line.

        Line-level and keyed on the note's name, because that is what the index
        is: one line per note, naming it. **A line that describes the note
        without naming it survives**, and `docs/reference/capabilities.md` says
        so rather than leaving somebody to assume otherwise. The index itself is
        never pruned against itself.
        """
        if row.name == INDEX_NAME:
            return
        index = await memory_repo.get_by_name(
            self.db,
            organization_id=row.organization_id,
            agent_id=row.agent_id,
            owner_key=row.owner_key,
            name=INDEX_NAME,
        )
        if index is None:
            return
        kept = [line for line in index.content.splitlines() if row.name not in line]
        if len(kept) == len(index.content.splitlines()):
            return
        await memory_repo.update(
            self.db,
            file=index,
            # Not `written_at`: the agent did not write this, and moving it would
            # put the index at the top of the person's own listing.
            update_data={"content": "\n".join(kept)},
        )

    async def _agent_names(self, agent_ids: set[UUID]) -> dict[UUID, str]:
        """Which agent wrote each note. Provenance, and the reason for the join."""
        if not agent_ids:
            return {}
        result = await self.db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))
        return {row[0]: row[1] for row in result.all()}

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
