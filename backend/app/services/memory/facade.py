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

Native memory is the only store (mem0 was removed, #2090), so one delete is the
whole erasure.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.memory_keys import INDEX_NAME, person_owner_key
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.memory import AgentMemoryFile
from app.db.models.memory_claim import MemoryClaim
from app.repositories import agent_repo, memory_claim, memory_repo, organization_repo
from app.schemas.memory import (
    MemoryClaimCorrect,
    MemoryClaimDetail,
    MemoryClaimList,
    MemoryClaimRead,
    MemoryErasureResult,
    MemoryNoteList,
    MemoryNoteRead,
)
from app.services.access import AGENT, resolve_access
from app.services.memory import _claims

logger = logging.getLogger(__name__)

_LIVE_STATUSES = ("current", "disputed")
_ALL_STATUSES = ("current", "disputed", "superseded", "merged", "retracted")


def _claim_read(row: MemoryClaim, names: dict[UUID, str]) -> MemoryClaimRead:
    return MemoryClaimRead(
        id=row.id,
        agent_id=row.agent_id,
        agent_name=names.get(row.agent_id) if row.agent_id else None,
        scope="profile" if row.agent_id is None else "agent",
        subject=row.subject,
        statement=row.statement,
        kind=row.kind,
        origin=row.origin,  # ty: ignore[invalid-argument-type]
        status=row.status,  # ty: ignore[invalid-argument-type]
        observed_at=row.observed_at,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        supersedes_id=row.supersedes_id,
        derived_from_count=len(row.derived_from or []),
    )


class MemoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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

    async def my_claims(
        self, ctx: AuthContext, *, skip: int, limit: int, history: bool
    ) -> MemoryClaimList:
        """The claims recorded about the caller, under every agent, current ones by default.

        `history` adds what was superseded, merged or retracted: the record of how
        each current claim came to say what it says.
        """
        statuses = _ALL_STATUSES if history else _LIVE_STATUSES
        rows, total = await memory_claim.list_for_owner(
            self.db,
            organization_id=ctx.organization_id,
            scope_key=person_owner_key(ctx.subject_id),
            statuses=statuses,
            skip=skip,
            limit=limit,
        )
        names = await self._agent_names({row.agent_id for row in rows if row.agent_id})
        return MemoryClaimList(items=[_claim_read(row, names) for row in rows], total=total)

    async def claim_detail(self, ctx: AuthContext, claim_id: UUID) -> MemoryClaimDetail:
        """One of the caller's claims with its ancestry, filtered to what they may read.

        The caller reads their own scope; a source that lives anywhere else - a copy
        another person shared into, say - is counted as withheld rather than shown.
        """
        row = await self._own_claim(ctx, claim_id)
        scope_key = person_owner_key(ctx.subject_id)
        found = await _claims.provenance(self.db, claim=row, readable_keys=[scope_key])
        related = [row, *found.sources, *([found.superseded] if found.superseded else [])]
        names = await self._agent_names({item.agent_id for item in related if item.agent_id})
        return MemoryClaimDetail(
            **_claim_read(row, names).model_dump(),
            sources=[_claim_read(item, names) for item in found.sources],
            withheld=found.withheld,
            superseded=_claim_read(found.superseded, names) if found.superseded else None,
        )

    async def correct_claim(
        self, ctx: AuthContext, claim_id: UUID, data: MemoryClaimCorrect
    ) -> MemoryClaimRead:
        """Replace one of the caller's claims with their own words, keeping its history."""
        row = await self._own_live_claim(ctx, claim_id)
        fixed = await _claims.correct(
            self.db,
            claim=row,
            statement=data.statement,
            author_user_id=ctx.subject_id,
            effective_from=data.effective_from,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.claim.corrected",
            target_type="memory_claim",
            target_id=str(claim_id),
            # Never the statements: an entry holding what it corrected keeps it.
            details={"replacement": str(fixed.id)},
        )
        names = await self._agent_names({fixed.agent_id} if fixed.agent_id else set())
        return _claim_read(fixed, names)

    async def retract_claim(self, ctx: AuthContext, claim_id: UUID) -> MemoryClaimRead:
        """Take one of the caller's claims out of use; sources and history stay."""
        row = await self._own_live_claim(ctx, claim_id)
        await _claims.retract(self.db, claim=row)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.claim.retracted",
            target_type="memory_claim",
            target_id=str(claim_id),
            details={},
        )
        names = await self._agent_names({row.agent_id} if row.agent_id else set())
        return _claim_read(row, names)

    async def _own_live_claim(self, ctx: AuthContext, claim_id: UUID) -> MemoryClaim:
        """One of the caller's claims that is still in use, for a change.

        History is read-only: retracting a superseded claim would rewrite when it stopped
        holding, and correcting one would supersede the unrelated current claim on the
        same subject.

        Raises:
            ConflictError: The claim is in the history.
        """
        row = await self._own_claim(ctx, claim_id)
        if row.status not in _LIVE_STATUSES:
            raise ConflictError(
                message="That claim is in the history and cannot be changed",
                details={"claim_id": claim_id, "status": row.status},
            )
        return row

    async def _own_claim(self, ctx: AuthContext, claim_id: UUID) -> MemoryClaim:
        """One claim, only if it is in the caller's own scope - a miss is a 404, never a 403."""
        row = await memory_claim.get_owned(
            self.db,
            organization_id=ctx.organization_id,
            scope_key=person_owner_key(ctx.subject_id),
            claim_id=claim_id,
        )
        if row is None:
            raise NotFoundError(message="Memory claim not found", details={"claim_id": claim_id})
        return row

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
        return MemoryNoteList(items=items, total=total)

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
        claims = await memory_claim.delete_for_scope(
            self.db, organization_id=ctx.organization_id, scope_key=owner_key
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.person.forgotten",
            target_type="user",
            target_id=str(user_id),
            details={"notes": notes, "claims": claims},
        )
        return MemoryErasureResult(notes_deleted=notes, claims_deleted=claims)

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
        claims = await memory_claim.delete_for_agent(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.agent.cleared",
            target_type="agent",
            target_id=str(agent_id),
            details={"notes": notes, "claims": claims},
        )
        return MemoryErasureResult(notes_deleted=notes, claims_deleted=claims)
