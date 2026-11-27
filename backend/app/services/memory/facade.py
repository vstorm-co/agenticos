"""Personal memory inspection, corrections and erasure.

A person may correct only their own notes. Agent-write timestamps remain intact;
corrections have separate audit entries. Organization authority does not grant
access to a colleague's personal memory.

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
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from app.core.memory_keys import (
    GROUP_PREFIX,
    INDEX_NAME,
    ORGANIZATION_PREFIX,
    group_owner_key,
    organization_owner_key,
    person_owner_key,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm, Scope
from app.db.locks import LockScope, hold_subject
from app.db.models.agent import Agent
from app.db.models.memory import AgentMemoryFile
from app.db.models.memory_claim import (
    MemoryClaim,
    MemoryObject,
    MemoryObjectBackfill,
    MemoryObjectMerge,
)
from app.repositories import (
    agent_repo,
    audit_log_repo,
    group_repo,
    member_repo,
    memory_claim,
    memory_repo,
    organization_repo,
    personal_data_repo,
)
from app.schemas.dataset import DatasetCaseContent, DatasetCaseRead
from app.schemas.decision_episode import DecisionEpisode, ImproveCaseReview
from app.schemas.memory import (
    MAX_AUTOMATIC_NOTE_CHARS,
    MAX_CONFLICT_CANDIDATES,
    MemoryClaimCorrect,
    MemoryClaimDetail,
    MemoryClaimEvidenceRead,
    MemoryClaimList,
    MemoryClaimRead,
    MemoryClaimShare,
    MemoryConflictResolve,
    MemoryErasureResult,
    MemoryInboxDecisionCount,
    MemoryInboxRuleRead,
    MemoryInboxRuleUpdate,
    MemoryLibrary,
    MemoryNoteAutoUpdate,
    MemoryNoteEdit,
    MemoryNoteList,
    MemoryNoteRead,
    MemoryNoteRestore,
    MemoryNoteRevisionList,
    MemoryNoteRevisionRead,
    MemoryNoteShare,
    MemoryObjectBackfillAdvance,
    MemoryObjectBackfillRead,
    MemoryObjectBackfillRun,
    MemoryObjectKind,
    MemoryObjectMergeCreate,
    MemoryObjectMergePage,
    MemoryObjectMergeRead,
    MemoryObjectPage,
    MemoryObjectRead,
    MemoryObjectTimeline,
    SharedMemoryNotePage,
    SharedMemoryNoteRead,
)
from app.services.access import AGENT, resolve_access
from app.services.background_jobs import enqueue
from app.services.dataset import DatasetService
from app.services.memory import _claims
from app.services.memory_inbox_policy import queue_inbox_change
from app.worker.jobs import BACKFILL_MEMORY_OBJECTS, BackfillMemoryObjects

logger = logging.getLogger(__name__)

_LIVE_STATUSES = ("current", "disputed")
_ALL_STATUSES = ("current", "disputed", "superseded", "merged", "retracted")


def _claim_read(row: MemoryClaim, names: dict[UUID, str]) -> MemoryClaimRead:
    scope: Literal["profile", "agent", "organization", "group"]
    if row.scope_key.startswith(ORGANIZATION_PREFIX):
        scope = "organization"
    elif row.scope_key.startswith(GROUP_PREFIX):
        scope = "group"
    else:
        scope = "profile" if row.agent_id is None else "agent"
    return MemoryClaimRead(
        id=row.id,
        object_id=row.object_id,
        agent_id=row.agent_id,
        agent_name=names.get(row.agent_id) if row.agent_id else None,
        scope=scope,
        subject=row.subject,
        statement=row.statement,
        value=row.value,
        kind=row.kind,
        origin=row.origin,  # ty: ignore[invalid-argument-type]
        status=row.status,  # ty: ignore[invalid-argument-type]
        observed_at=row.observed_at,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        supersedes_id=row.supersedes_id,
        derived_from_count=0 if scope in ("organization", "group") else len(row.derived_from or []),
        episode=DecisionEpisode.model_validate(row.episode) if row.episode is not None else None,
    )


def _merge_read(merge: MemoryObjectMerge, source: MemoryObject) -> MemoryObjectMergeRead:
    return MemoryObjectMergeRead(
        id=merge.id,
        source=MemoryObjectRead.model_validate(source, from_attributes=True),
        target_id=merge.target_id,
        merged_at=merge.merged_at,
    )


def _backfill_parent_ids(claim: MemoryClaim) -> set[UUID]:
    if len(claim.derived_from) > 100:
        return set()
    try:
        ids = {UUID(str(parent)) for parent in claim.derived_from}
    except ValueError:
        return set()
    if claim.supersedes_id is not None:
        ids.add(claim.supersedes_id)
    return ids


class MemoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def mine(self, ctx: AuthContext, *, skip: int, limit: int, q: str = "") -> MemoryNoteList:
        """What the agents in this organization have written down about the caller.

        No permission, because there is none to ask for: this is the caller's own
        store, and the answer is the same for a Viewer and an Owner. Suppressed
        notes are included - they are the person's, and a view that hid what they
        had suppressed would be one they could not restore anything from.
        """
        return await self._notes_for(
            ctx.organization_id,
            person_owner_key(ctx.subject_id),
            skip=skip,
            limit=limit,
            q=q.strip(),
        )

    async def my_claims(
        self,
        ctx: AuthContext,
        *,
        skip: int,
        limit: int,
        history: bool,
        q: str = "",
        kind: Literal["fact", "preference", "decision"] | None = None,
        scope: Literal["profile", "agent"] | None = None,
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
            in_effect=not history,
            q=q.strip(),
            kind=kind,
            scope=scope,
        )
        names = await self._agent_names({row.agent_id for row in rows if row.agent_id})
        return MemoryClaimList(items=[_claim_read(row, names) for row in rows], total=total)

    async def _library_keys(self, ctx: AuthContext, library: MemoryLibrary) -> list[str]:
        if ctx.subject_is_publisher_fallback or ctx.key_scopes is not None:
            raise AuthorizationError(message="The memory library requires a member session")
        if library == "personal":
            return [person_owner_key(ctx.subject_id)]
        if not ctx.has(Perm.CONTEXT_VIEW):
            raise AuthorizationError(message="Reading shared memory requires context:view")
        memberships = await group_repo.list_memberships_in_org(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )
        return [
            organization_owner_key(ctx.organization_id),
            *(group_owner_key(membership.group_id) for membership in memberships),
        ]

    async def objects(
        self,
        ctx: AuthContext,
        *,
        library: MemoryLibrary,
        kind: MemoryObjectKind | None,
        q: str,
        cursor: UUID | None,
        limit: int,
        merge_target: UUID | None = None,
    ) -> MemoryObjectPage:
        keys = await self._library_keys(ctx, library)
        if merge_target is not None:
            target = await self._object(ctx, keys, merge_target, follow_merge=True)
            keys = [target.scope_key]
            kind = MemoryObjectRead.model_validate(target, from_attributes=True).kind
            merge_target = target.id
        rows = await memory_claim.list_objects(
            self.db,
            organization_id=ctx.organization_id,
            scope_keys=keys,
            kind=kind,
            q=q.strip(),
            cursor=cursor,
            limit=limit + 1,
            merge_target=merge_target,
        )
        return MemoryObjectPage(
            items=[
                MemoryObjectRead.model_validate(row, from_attributes=True) for row in rows[:limit]
            ],
            next_cursor=rows[limit - 1].id if len(rows) > limit else None,
        )

    async def object_timeline(
        self,
        ctx: AuthContext,
        *,
        library: MemoryLibrary,
        object_id: UUID,
        as_of: datetime | None,
        known_at: datetime | None,
        cursor: UUID | None,
        limit: int,
    ) -> MemoryObjectTimeline:
        keys = await self._library_keys(ctx, library)
        if known_at is not None and as_of is None:
            raise BadRequestError(message="Choose an effective date before setting known_at")
        entity = await self._object(ctx, keys, object_id, follow_merge=True)
        rows = await memory_claim.object_claims(
            self.db,
            organization_id=ctx.organization_id,
            scope_key=entity.scope_key,
            object_id=entity.id,
            as_of=as_of,
            known_at=known_at,
            cursor=cursor,
            limit=limit + 1,
        )
        page = rows[:limit]
        states = (
            await memory_claim.states_known_at(self.db, rows=page, known_at=known_at)
            if known_at is not None
            else {}
        )
        return MemoryObjectTimeline(
            object=MemoryObjectRead.model_validate(entity, from_attributes=True),
            items=[
                _claim_read(row, {}).model_copy(
                    update={
                        "status": state.status,
                        "effective_to": state.effective_to,
                    }
                )
                if (state := states.get(row.id)) is not None
                else _claim_read(row, {})
                for row in page
            ],
            next_cursor=rows[limit - 1].id if len(rows) > limit else None,
        )

    async def _object(
        self, ctx: AuthContext, keys: list[str], object_id: UUID, *, follow_merge: bool = False
    ) -> MemoryObject:
        entity = await memory_claim.get_object(
            self.db,
            organization_id=ctx.organization_id,
            object_id=object_id,
            scope_keys=keys,
            follow_merge=follow_merge,
        )
        if entity is None:
            raise NotFoundError(message="Memory object not found")
        return entity

    async def _object_edit_keys(self, ctx: AuthContext, library: MemoryLibrary) -> list[str]:
        keys = await self._library_keys(ctx, library)
        if current_impersonator() is not None or (
            library == "organization" and ctx.scope_for(Perm.CONTEXT_EDIT) != Scope.ALL
        ):
            raise AuthorizationError(message="Editing shared memory objects requires context:edit")
        return keys

    async def object_merges(
        self,
        ctx: AuthContext,
        *,
        library: MemoryLibrary,
        target_id: UUID,
        cursor: UUID | None,
        limit: int,
    ) -> MemoryObjectMergePage:
        keys = await self._library_keys(ctx, library)
        target = await self._object(ctx, keys, target_id, follow_merge=True)
        rows = await memory_claim.active_object_merges(
            self.db,
            target_id=target.id,
            cursor=cursor,
            limit=limit + 1,
        )
        return MemoryObjectMergePage(
            items=[_merge_read(merge, source) for merge, source in rows[:limit]],
            next_cursor=rows[limit - 1][0].id if len(rows) > limit else None,
        )

    async def merge_objects(
        self,
        ctx: AuthContext,
        *,
        library: MemoryLibrary,
        target_id: UUID,
        data: MemoryObjectMergeCreate,
    ) -> MemoryObjectMergeRead:
        keys = await self._object_edit_keys(ctx, library)
        target = await self._object(ctx, keys, target_id)
        await _claims._hold_scope(
            self.db, organization_id=ctx.organization_id, scope_key=target.scope_key
        )
        target = await self._object(ctx, keys, target_id)
        source = await self._object(ctx, keys, data.source_id)
        if (
            target.id == source.id
            or target.kind != source.kind
            or target.scope_key != source.scope_key
        ):
            raise BadRequestError(message="Choose distinct objects of the same type and audience")
        merge = await memory_claim.merge_objects(self.db, source_id=source.id, target_id=target.id)
        if merge is None:
            raise ConflictError(
                message="Undo the existing merge before making this object an alias"
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.object.merged",
            target_type="memory_object_merge",
            target_id=str(merge.id),
            details={"source_id": str(source.id), "target_id": str(target.id)},
        )
        return _merge_read(merge, source)

    async def undo_object_merge(
        self,
        ctx: AuthContext,
        *,
        library: MemoryLibrary,
        target_id: UUID,
        merge_id: UUID,
    ) -> None:
        keys = await self._object_edit_keys(ctx, library)
        target = await self._object(ctx, keys, target_id, follow_merge=True)
        await _claims._hold_scope(
            self.db, organization_id=ctx.organization_id, scope_key=target.scope_key
        )
        target = await self._object(ctx, keys, target_id, follow_merge=True)
        merge = await memory_claim.active_merge(self.db, merge_id=merge_id, target_id=target.id)
        if merge is None:
            raise NotFoundError(message="Active memory object merge not found")
        await memory_claim.undo_object_merge(self.db, merge)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.object.merge_undone",
            target_type="memory_object_merge",
            target_id=str(merge.id),
            details={"target_id": str(target.id)},
        )

    @staticmethod
    def _require_memory_owner(ctx: AuthContext) -> None:
        if (
            ctx.role != OrgRoleName.OWNER
            or not ctx.acts_in_person
            or ctx.key_scopes is not None
            or ctx.subject_is_publisher_fallback
            or current_impersonator() is not None
        ):
            raise AuthorizationError(
                message="This operation requires a signed-in organization owner"
            )

    async def object_backfill_status(self, ctx: AuthContext) -> MemoryObjectBackfillRead | None:
        self._require_memory_owner(ctx)
        state = await memory_claim.backfill_state(self.db, organization_id=ctx.organization_id)
        return (
            MemoryObjectBackfillRead.model_validate(state, from_attributes=True) if state else None
        )

    async def _start_object_backfill(
        self,
        organization_id: UUID,
        *,
        restart: bool,
    ) -> MemoryObjectBackfill:
        state = await memory_claim.backfill_state(
            self.db, organization_id=organization_id, start=True
        )
        assert state is not None  # The repository creates and locks the tenant checkpoint.
        if restart:
            if state.completed_at is None:
                raise ConflictError(message="Resume the active backfill before starting a new scan")
            state.cutoff = datetime.now(UTC)
            state.cursor_at = state.cursor_id = state.completed_at = None
            state.scanned = state.linked = 0
        return state

    async def _queue_object_backfill(
        self,
        state: MemoryObjectBackfill,
        *,
        requested_by: UUID,
    ) -> None:
        key = f"memory-object-backfill:{state.organization_id}"
        await enqueue(
            self.db,
            BACKFILL_MEMORY_OBJECTS,
            BackfillMemoryObjects(
                organization_id=state.organization_id,
                requested_by=requested_by,
                cutoff=state.cutoff,
            ),
            organization_id=state.organization_id,
            dedupe_key=f"{key}:{state.cutoff.isoformat()}:{requested_by}",
            concurrency_key=key,
        )

    async def run_object_backfill(
        self,
        ctx: AuthContext,
        data: MemoryObjectBackfillRun,
    ) -> MemoryObjectBackfillRead:
        self._require_memory_owner(ctx)
        state = await self._start_object_backfill(ctx.organization_id, restart=data.restart)
        if state.completed_at is None:
            await self._queue_object_backfill(state, requested_by=ctx.subject_id)
        return MemoryObjectBackfillRead.model_validate(state, from_attributes=True)

    async def continue_object_backfill(self, payload: BackfillMemoryObjects) -> int:
        member = await member_repo.get_active(
            self.db,
            organization_id=payload.organization_id,
            user_id=payload.requested_by,
        )
        if member is None or member.role != OrgRoleName.OWNER:
            return 0
        state = await self._start_object_backfill(payload.organization_id, restart=False)
        if state.cutoff != payload.cutoff or state.completed_at is not None:
            return 0
        before = state.scanned
        await self._scan_object_backfill(state, limit=200)
        if state.completed_at is None:
            await self._queue_object_backfill(state, requested_by=payload.requested_by)
        return state.scanned - before

    async def advance_object_backfill(
        self,
        ctx: AuthContext,
        data: MemoryObjectBackfillAdvance,
    ) -> MemoryObjectBackfillRead:
        self._require_memory_owner(ctx)
        state = await self._start_object_backfill(ctx.organization_id, restart=data.restart)
        if state.completed_at is None:
            await self._scan_object_backfill(state, limit=data.limit)
        return MemoryObjectBackfillRead.model_validate(state, from_attributes=True)

    async def _scan_object_backfill(self, state: MemoryObjectBackfill, *, limit: int) -> None:
        rows = await memory_claim.unlinked_object_page(self.db, state, limit=limit)
        parents = {claim.id: _backfill_parent_ids(claim) for claim in rows}
        external = await memory_claim.external_objects_for_claims(
            self.db,
            organization_id=state.organization_id,
            claim_ids=set().union(*parents.values()),
        )
        links: dict[UUID, UUID] = {}
        for claim in rows:
            claim_parents = parents[claim.id]
            if not claim_parents or not claim_parents <= external.keys():
                continue
            identities = {external[parent] for parent in claim_parents}
            if len(identities) == 1:
                scope, agent, subject, object_id = identities.pop()
                if (scope, agent, subject) == (claim.scope_key, claim.agent_id, claim.subject):
                    links[claim.id] = object_id
        await memory_claim.link_backfilled_claims(
            self.db,
            organization_id=state.organization_id,
            links=links,
        )
        state.linked += len(links)
        if rows:
            state.cursor_at, state.cursor_id = rows[-1].created_at, rows[-1].id
            state.scanned += len(rows)
        if len(rows) < limit:
            state.completed_at = datetime.now(UTC)
        await self.db.flush()

    async def inbox_rule(self, ctx: AuthContext) -> MemoryInboxRuleRead:
        self._require_memory_owner(ctx)
        row = await memory_claim.inbox_rule(self.db, organization_id=ctx.organization_id)
        if row is None:
            return MemoryInboxRuleRead(
                version=0,
                mode="off",
                sources=["gmail", "webhook", "reviewed"],
                recipient_ids=[],
                include_review=False,
            )
        return MemoryInboxRuleRead.model_validate(row, from_attributes=True)

    async def update_inbox_rule(
        self,
        ctx: AuthContext,
        data: MemoryInboxRuleUpdate,
    ) -> MemoryInboxRuleRead:
        self._require_memory_owner(ctx)
        recipient_ids = sorted(set(data.recipient_ids))
        sources = sorted({str(source) for source in data.sources})
        if data.mode != "off" and (not recipient_ids or not sources):
            raise BadRequestError(message="Select at least one active recipient and source")
        active = await member_repo.get_active_ids(
            self.db,
            organization_id=ctx.organization_id,
            user_ids=recipient_ids,
        )
        if len(active) != len(recipient_ids):
            raise BadRequestError(message="Inbox recipients must be active organization members")
        rule = await memory_claim.inbox_rule(
            self.db, organization_id=ctx.organization_id, edit=True
        )
        assert rule is not None  # The repository creates and locks the tenant's rule on first edit.
        if rule.version != data.expected_version:
            raise ConflictError(message="The Inbox rule changed; reload before editing it")
        rule.version += 1
        rule.mode = data.mode
        rule.recipient_ids = recipient_ids
        rule.sources = sources
        rule.include_review = data.include_review
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.inbox_rule.updated",
            target_type="organization",
            target_id=str(ctx.organization_id),
            details={
                "version": rule.version,
                "mode": rule.mode,
                "recipient_count": len(recipient_ids),
            },
        )
        await self.db.flush()
        return MemoryInboxRuleRead.model_validate(rule, from_attributes=True)

    async def inbox_decision_counts(
        self,
        ctx: AuthContext,
        version: int,
    ) -> list[MemoryInboxDecisionCount]:
        self._require_memory_owner(ctx)
        rows = await memory_claim.inbox_decision_counts(
            self.db,
            organization_id=ctx.organization_id,
            rule_version=version,
        )
        return [
            MemoryInboxDecisionCount.model_validate(
                {"change": change, "outcome": outcome, "count": count}
            )
            for change, outcome, count in rows
        ]

    async def _publication_target(self, ctx: AuthContext, group_id: UUID | None) -> str:
        await self._library_keys(ctx, "personal")
        if ctx.scope_for(Perm.CONTEXT_EDIT) != Scope.ALL:
            raise AuthorizationError(message="Publishing shared memory requires context:edit")
        if group_id is None:
            return organization_owner_key(ctx.organization_id)
        group = await group_repo.get(
            self.db, organization_id=ctx.organization_id, group_id=group_id, for_update=True
        )
        if group is None:
            raise NotFoundError(message="Group not found")
        return group_owner_key(group.id)

    async def publish_claim(
        self, ctx: AuthContext, claim_id: UUID, data: MemoryClaimShare
    ) -> MemoryClaimRead:
        target = await self._publication_target(ctx, data.group_id)
        source = await self._own_live_claim(ctx, claim_id)
        claim = await _claims.share(
            self.db,
            claim=source,
            to=memory_claim.ClaimScope(target),
            author_user_id=ctx.subject_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.claim.shared",
            target_type="memory_claim",
            target_id=str(claim.id),
            details={"target": target},
        )
        return _claim_read(claim, {})

    async def publish_note(
        self, ctx: AuthContext, note_id: UUID, data: MemoryNoteShare
    ) -> SharedMemoryNoteRead:
        target = await self._publication_target(ctx, data.group_id)
        await hold_subject(self.db, LockScope.PERSONAL_DATA_PER_USER, ctx.subject_id)
        note = await self._own_note(ctx, note_id, for_update=True)
        if note.deactivated_at is not None or note.updated_at != data.expected_updated_at:
            raise ConflictError(message="The note changed. Open it again before sharing.")
        shared = await memory_claim.publish_note(
            self.db,
            organization_id=ctx.organization_id,
            source_id=note.id,
            scope_key=target,
            name=note.name,
            content=note.content,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.note.shared",
            target_type="memory_file",
            target_id=str(shared.id),
            details={"target": target},
        )
        return SharedMemoryNoteRead.model_validate(shared, from_attributes=True)

    async def shared_notes(
        self,
        ctx: AuthContext,
        *,
        cursor: UUID | None,
        limit: int,
    ) -> SharedMemoryNotePage:
        keys = await self._library_keys(ctx, "organization")
        rows = await memory_claim.shared_notes(
            self.db, organization_id=ctx.organization_id, keys=keys, cursor=cursor, limit=limit + 1
        )
        return SharedMemoryNotePage(
            items=[
                SharedMemoryNoteRead.model_validate(row, from_attributes=True)
                for row in rows[:limit]
            ],
            next_cursor=rows[limit - 1].id if len(rows) > limit else None,
        )

    async def shared_claims(
        self, ctx: AuthContext, *, q: str, limit: int, skip: int, disputed: bool = False
    ) -> MemoryClaimList:
        keys = await self._library_keys(ctx, "organization")
        rows, total = await memory_claim.list_for_owner(
            self.db,
            organization_id=ctx.organization_id,
            scope_key=keys,
            statuses=("disputed",) if disputed else _LIVE_STATUSES,
            in_effect=True,
            q=q.strip(),
            skip=skip,
            limit=limit,
        )
        return MemoryClaimList(items=[_claim_read(row, {}) for row in rows], total=total)

    async def _shared_claim(self, ctx: AuthContext, claim_id: UUID) -> MemoryClaim:
        keys = await self._library_keys(ctx, "organization")
        claim = await memory_claim.get(
            self.db, organization_id=ctx.organization_id, claim_id=claim_id
        )
        if claim is None or claim.scope_key not in keys:
            raise NotFoundError(message="Memory claim not found")
        return claim

    async def _conflict_candidates(
        self, claim: MemoryClaim, *, lock: bool = False
    ) -> list[MemoryClaim]:
        if claim.object_id is None or claim.subject is None or claim.status not in _LIVE_STATUSES:
            return []
        rows = await memory_claim.about_subject(
            self.db,
            organization_id=claim.organization_id,
            scope=memory_claim.ClaimScope(claim.scope_key, claim.agent_id),
            subject=claim.subject,
            object_id=claim.object_id,
            in_effect=True,
            lock=lock,
            limit=MAX_CONFLICT_CANDIDATES + 1,
        )
        if (
            len(rows) > MAX_CONFLICT_CANDIDATES
            or not any(row.id == claim.id for row in rows)
            or not any(row.status == "disputed" for row in rows)
        ):
            return []
        return rows

    async def resolve_shared_conflict(
        self, ctx: AuthContext, claim_id: UUID, data: MemoryConflictResolve
    ) -> MemoryClaimRead:
        if ctx.scope_for(Perm.CONTEXT_EDIT) != Scope.ALL:
            raise AuthorizationError(message="Resolving shared memory requires context:edit")
        claim = await self._shared_claim(ctx, claim_id)
        await _claims._hold_scope(
            self.db, organization_id=ctx.organization_id, scope_key=claim.scope_key
        )
        claim = await self._shared_claim(ctx, claim_id)
        peers = await self._conflict_candidates(claim, lock=True)
        if not peers or {row.id for row in peers} != set(data.candidate_ids):
            raise ConflictError(message="Memory conflict changed; reload before resolving it")
        previous = None
        if claim.status == "disputed" and claim.subject == "deadline":
            alternatives = [row for row in peers if row.id != claim.id]
            accepted = await memory_claim.previously_accepted(
                self.db,
                candidate_ids=[row.id for row in alternatives],
            )
            previous = next((row for row in reversed(alternatives) if row.id in accepted), None)
        now = datetime.now(UTC)
        for row in peers:
            if row.id == claim_id:
                await memory_claim.set_status(self.db, row, "current")
            elif row.status == "current":
                await memory_claim.set_status(self.db, row, "superseded", effective_to=now)
            else:
                await memory_claim.set_status(self.db, row, "retracted")
        await memory_claim.bump_revision(
            self.db, organization_id=ctx.organization_id, scope_key=claim.scope_key
        )
        await queue_inbox_change(self.db, claim=claim, previous=previous)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.conflict.resolved",
            target_type="memory_claim",
            target_id=str(claim_id),
            details={"alternatives": len(peers) - 1},
        )
        return _claim_read(claim, {})

    async def shared_claim_detail(self, ctx: AuthContext, claim_id: UUID) -> MemoryClaimDetail:
        claim = await self._shared_claim(ctx, claim_id)
        # A claim's sources may live in a different shared audience.
        keys = await self._library_keys(ctx, "organization")
        found = await _claims.provenance(self.db, claim=claim, readable_keys=keys)
        return MemoryClaimDetail(
            **_claim_read(claim, {}).model_dump(),
            evidence=[
                MemoryClaimEvidenceRead(
                    kind="webhook" if event.provider == "webhook" else "gmail",
                    source_id=str(event.id)
                    if event.workflow_delivery_id is not None
                    else event.delivery_id,
                    quote=event.quote,
                    occurred_at=event.received_at,
                )
                for event in await memory_claim.mail_evidence(self.db, claim=claim)
            ],
            sources=[_claim_read(row, {}) for row in found.sources],
            superseded=_claim_read(found.superseded, {}) if found.superseded else None,
            conflicts=[_claim_read(row, {}) for row in await self._conflict_candidates(claim)],
        )

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
            evidence=[
                MemoryClaimEvidenceRead(
                    kind="message",
                    source_id=f"message:{item.message_id}",
                    quote=item.quote,
                    occurred_at=item.occurred_at,
                )
                for item in await memory_claim.message_evidence(self.db, row.id)
            ],
            sources=[_claim_read(item, names) for item in found.sources],
            withheld=found.withheld,
            superseded=_claim_read(found.superseded, names) if found.superseded else None,
        )

    async def improve_case(
        self, ctx: AuthContext, claim_id: UUID, data: ImproveCaseReview
    ) -> DatasetCaseRead:
        """Add only human-reviewed text from a decision episode to a dataset.

        The caller needs `datasets:edit` on that dataset; this grants no dataset
        access and turns no private episode into a shared rule. The case records the
        caller as who asked it, so erasing them anonymises it like any case taken
        from their conversations.
        """
        row = await self._own_live_claim(ctx, claim_id)
        if row.kind != "decision" or row.episode is None:
            raise BadRequestError(message="Choose a recorded decision episode")
        case = await DatasetService(self.db).add_reviewed_case(
            ctx,
            data.dataset_id,
            DatasetCaseContent(
                input=data.input, reference_answer=data.reference_answer, tags=["decision-episode"]
            ),
            asked_by=ctx.subject_id,
            source_run_id=row.source_run_id,
            source_conversation_id=row.source_conversation_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.episode.exported",
            target_type="memory_claim",
            target_id=str(row.id),
            details={"dataset_id": str(data.dataset_id), "case_id": str(case.id)},
        )
        return case

    async def correct_claim(
        self, ctx: AuthContext, claim_id: UUID, data: MemoryClaimCorrect
    ) -> MemoryClaimRead:
        """Replace one of the caller's claims with their own words, keeping its history."""
        if data.historical:
            await self._library_keys(ctx, "personal")
            if data.effective_from is not None:
                raise BadRequestError(message="Historical corrections keep the original interval")
            row = await self._own_claim(ctx, claim_id)
            fixed = await _claims.amend_observation(
                self.db,
                claim=row,
                statement=data.statement,
                value=data.value,
                author_user_id=ctx.subject_id,
                episode=data.episode,
            )
        else:
            row = await self._own_live_claim(ctx, claim_id)
            fixed = await _claims.correct(
                self.db,
                claim=row,
                statement=data.statement,
                value=data.value,
                author_user_id=ctx.subject_id,
                effective_from=data.effective_from,
                episode=data.episode,
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
        if not _claims.mutable(row):
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

    async def edit_note(
        self, ctx: AuthContext, file_id: UUID, data: MemoryNoteEdit
    ) -> MemoryNoteRead:
        """Correct only the subject's own note, refusing a stale editor revision."""
        row = await memory_repo.get_owned(
            self.db,
            organization_id=ctx.organization_id,
            owner_key=person_owner_key(ctx.subject_id),
            file_id=file_id,
            for_update=True,
        )
        if row is None:
            raise NotFoundError(message="Memory note not found", details={"file_id": file_id})
        if row.updated_at != data.expected_updated_at:
            raise AlreadyExistsError(
                message="This note changed. Reopen it before saving your correction."
            )
        await memory_repo.replace_content(
            self.db, file=row, content=data.content, changed_by="person"
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.note.corrected",
            target_type="memory_file",
            target_id=str(file_id),
            details={"agent_id": str(row.agent_id), "fields": ["content"]},
        )
        names = await self._agent_names({row.agent_id})
        return MemoryNoteRead.model_validate(row).model_copy(
            update={"agent_name": names.get(row.agent_id)}
        )

    async def set_note_auto_update(
        self, ctx: AuthContext, file_id: UUID, data: MemoryNoteAutoUpdate
    ) -> MemoryNoteRead:
        row = await self._own_note(ctx, file_id, for_update=True)
        if row.updated_at != data.expected_updated_at:
            raise ConflictError(
                message="The note changed. Open it again before changing automatic updates."
            )
        if data.enabled and (
            row.name.casefold() == INDEX_NAME.casefold()
            or len(row.content) > MAX_AUTOMATIC_NOTE_CHARS
        ):
            raise ConflictError(
                message="Automatic updates require a working note of at most 4000 characters."
            )
        if row.auto_update != data.enabled:
            changes: dict[str, object] = {"auto_update": data.enabled}
            if data.enabled:
                # A job already queued before the owner's choice cannot use the new consent.
                changes["maintenance_source_at"] = datetime.now(UTC)
            await memory_repo.update(self.db, file=row, update_data=changes)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.note.auto_update",
            target_type="memory_file",
            target_id=str(file_id),
            details={"enabled": data.enabled},
        )
        return await self._note_read(row)

    async def note_revisions(
        self, ctx: AuthContext, file_id: UUID, *, skip: int, limit: int
    ) -> MemoryNoteRevisionList:
        await self._own_note(ctx, file_id)
        rows, total = await memory_repo.note_revisions(
            self.db,
            organization_id=ctx.organization_id,
            note_id=file_id,
            skip=skip,
            limit=limit,
        )
        return MemoryNoteRevisionList(
            items=[MemoryNoteRevisionRead.model_validate(row) for row in rows], total=total
        )

    async def restore_note_revision(
        self, ctx: AuthContext, file_id: UUID, revision_id: UUID, data: MemoryNoteRestore
    ) -> MemoryNoteRead:
        row = await self._own_note(ctx, file_id, for_update=True)
        if row.updated_at != data.expected_updated_at:
            raise ConflictError(
                message="The note changed. Open it again before restoring a previous version."
            )
        revision = await memory_repo.note_revision(
            self.db, organization_id=ctx.organization_id, note_id=file_id, revision_id=revision_id
        )
        if revision is None:
            raise NotFoundError(message="Memory note revision not found")
        await memory_repo.replace_content(
            self.db, file=row, content=revision.content, changed_by="restore"
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.note.revision.restored",
            target_type="memory_file",
            target_id=str(file_id),
            details={"revision_id": str(revision_id)},
        )
        return await self._note_read(row)

    async def _note_read(self, row: AgentMemoryFile) -> MemoryNoteRead:
        names = await self._agent_names({row.agent_id})
        return MemoryNoteRead.model_validate(row).model_copy(
            update={"agent_name": names.get(row.agent_id)}
        )

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
        row = await self._own_note(ctx, file_id, for_update=True)
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
        row = await self._own_note(ctx, file_id, for_update=True)
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

    async def _own_note(
        self, ctx: AuthContext, file_id: UUID, *, for_update: bool = False
    ) -> AgentMemoryFile:
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
            for_update=for_update,
        )
        if row is None:
            raise NotFoundError(message="Memory note not found", details={"file_id": file_id})
        return row

    async def _notes_for(
        self, organization_id: UUID, owner_key: str, *, skip: int = 0, limit: int = 50, q: str = ""
    ) -> MemoryNoteList:
        """One store's page, with the agent names and the stores this cannot reach."""
        rows, total = await memory_repo.list_for_person(
            self.db,
            organization_id=organization_id,
            owner_key=owner_key,
            skip=skip,
            limit=limit,
            q=q,
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
        await hold_subject(self.db, LockScope.PERSONAL_DATA_PER_USER, user_id)
        owner_key = person_owner_key(user_id)
        notes = await memory_repo.delete_for_person(
            self.db, organization_id=ctx.organization_id, owner_key=owner_key
        )
        claims = await memory_claim.delete_for_scope(
            self.db, organization_id=ctx.organization_id, scope_key=owner_key
        )
        await personal_data_repo.forget_system_runs_of(
            self.db, user_id, organization_id=ctx.organization_id
        )
        await personal_data_repo.forget_briefings_of(
            self.db, user_id, organization_id=ctx.organization_id
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.person.forgotten",
            target_type="user",
            target_id=str(user_id),
            details={
                "notes": notes,
                "claims": claims,
                **await audit_log_repo.erasure_marks(self.db),
            },
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
        await hold_subject(self.db, LockScope.MEMORY_PER_AGENT, agent_id)
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
            details={
                "notes": notes,
                "claims": claims,
                **await audit_log_repo.erasure_marks(self.db),
            },
        )
        return MemoryErasureResult(notes_deleted=notes, claims_deleted=claims)
