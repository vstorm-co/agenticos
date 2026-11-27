"""Memory routes: what a person may see of their own, and what erasure removes.

People may inspect and correct their own memory notes. Shared standing knowledge
still belongs in `context`; editing an agent does not expose another person's notes.
The self-service and inspection surfaces preserve distinct authority:

- **Your own store, always.** No permission to ask for: the answer is the same
  for a Viewer and an Owner, because it is the caller's own. They may suppress a
  note, restore it, or delete it.
- **Somebody else's, only a deployment administrator.** Reading what every agent
  has learned about a named colleague is a surveillance affordance, and an
  organization role is not the party a subject-access request reaches. An Owner
  or Admin does not get this by role, and neither does a grant on the agent.

No route here carries a `require(...)` gate, for the reasons this project
distinguishes. Clearing one agent is a per-resource act, so a role gate
would refuse a viewer holding an explicit grant on that agent before
`resolve_access` could widen it. Forgetting a person is not an agent act at all -
it is somebody erasing themselves, or `MEMBERS_MANAGE` erasing a member - and the
service is where that is decided.
"""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import AwareDatetime

from app.api.deps import Auth, MemorySvc
from app.schemas.dataset import DatasetCaseRead
from app.schemas.decision_episode import ImproveCaseReview
from app.schemas.memory import (
    MemoryClaimCorrect,
    MemoryClaimDetail,
    MemoryClaimList,
    MemoryClaimRead,
    MemoryClaimShare,
    MemoryConflictResolve,
    MemoryErasureResult,
    MemoryInboxDecisionCount,
    MemoryInboxRuleRead,
    MemoryInboxRuleUpdate,
    MemoryInboxShadowCount,
    MemoryLibrary,
    MemoryNoteAutoUpdate,
    MemoryNoteEdit,
    MemoryNoteList,
    MemoryNoteRead,
    MemoryNoteRestore,
    MemoryNoteRevisionList,
    MemoryNoteShare,
    MemoryNoteUpdate,
    MemoryObjectBackfillAdvance,
    MemoryObjectBackfillRead,
    MemoryObjectBackfillRun,
    MemoryObjectKind,
    MemoryObjectMergeCreate,
    MemoryObjectMergePage,
    MemoryObjectMergeRead,
    MemoryObjectPage,
    MemoryObjectTimeline,
    MemorySourceAuthorityRead,
    MemorySourceAuthorityUpdate,
    SharedMemoryNotePage,
    SharedMemoryNoteRead,
)

router = APIRouter()


@router.get("/objects", response_model=MemoryObjectPage)
async def memory_objects(
    service: MemorySvc,
    ctx: Auth,
    library: MemoryLibrary = Query("personal"),
    kind: MemoryObjectKind | None = Query(None),
    q: str = Query("", max_length=160),
    cursor: UUID | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
    merge_target: UUID | None = Query(None),
) -> Any:
    """Browse business objects in the caller's personal or shared library."""
    return await service.objects(
        ctx,
        library=library,
        kind=kind,
        q=q,
        cursor=cursor,
        limit=limit,
        merge_target=merge_target,
    )


@router.get("/source-authorities", response_model=list[MemorySourceAuthorityRead])
async def memory_source_authorities(service: MemorySvc, ctx: Auth) -> Any:
    """List the organization's approved workflows for individual memory properties."""
    return await service.source_authorities(ctx)


@router.put("/source-authorities", response_model=MemorySourceAuthorityRead)
async def set_memory_source_authority(
    data: MemorySourceAuthorityUpdate, service: MemorySvc, ctx: Auth
) -> Any:
    """Assign or clear the workflow that can advance a specific memory property."""
    return await service.update_source_authority(ctx, data)


@router.get("/inbox-rule", response_model=MemoryInboxRuleRead)
async def memory_inbox_rule(service: MemorySvc, ctx: Auth) -> Any:
    """Read the organization's versioned commitment deadline routing rule."""
    return await service.inbox_rule(ctx)


@router.put("/inbox-rule", response_model=MemoryInboxRuleRead)
async def set_memory_inbox_rule(data: MemoryInboxRuleUpdate, service: MemorySvc, ctx: Auth) -> Any:
    """Set the sources, recipients and delivery or shadow mode for new changes."""
    return await service.update_inbox_rule(ctx, data)


@router.get("/inbox-rule/decisions", response_model=list[MemoryInboxDecisionCount])
async def memory_inbox_decisions(
    service: MemorySvc,
    ctx: Auth,
    version: int = Query(ge=1),
) -> Any:
    """Summarize the rule's outcomes without disclosing object or source content."""
    return await service.inbox_decision_counts(ctx, version)


@router.get("/inbox-rule/shadow-model", response_model=list[MemoryInboxShadowCount])
async def memory_inbox_shadow_model(
    service: MemorySvc, ctx: Auth, version: int = Query(ge=1)
) -> Any:
    """Compare shadow model recommendations with the deterministic decision."""
    return await service.inbox_shadow_counts(ctx, version)


@router.get("/object-backfill", response_model=MemoryObjectBackfillRead | None)
async def object_backfill_status(service: MemorySvc, ctx: Auth) -> Any:
    """Read the organization's last committed object backfill checkpoint."""
    return await service.object_backfill_status(ctx)


@router.post(
    "/object-backfill/run",
    response_model=MemoryObjectBackfillRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_object_backfill(
    data: MemoryObjectBackfillRun,
    service: MemorySvc,
    ctx: Auth,
) -> Any:
    """Queue the next batch and resume processing from the committed checkpoint."""
    return await service.run_object_backfill(ctx, data)


@router.post("/object-backfill/advance", response_model=MemoryObjectBackfillRead)
async def advance_object_backfill(
    data: MemoryObjectBackfillAdvance, service: MemorySvc, ctx: Auth
) -> Any:
    """Advance one bounded batch; repeat until completed_at is set."""
    return await service.advance_object_backfill(ctx, data)


@router.get("/objects/{object_id}/merges", response_model=MemoryObjectMergePage)
async def memory_object_merges(
    object_id: UUID,
    service: MemorySvc,
    ctx: Auth,
    library: MemoryLibrary = Query("personal"),
    cursor: UUID | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
) -> Any:
    """List active identity aliases for an object."""
    return await service.object_merges(
        ctx, library=library, target_id=object_id, cursor=cursor, limit=limit
    )


@router.post(
    "/objects/{object_id}/merges",
    response_model=MemoryObjectMergeRead,
    status_code=status.HTTP_201_CREATED,
)
async def merge_memory_objects(
    object_id: UUID,
    data: MemoryObjectMergeCreate,
    service: MemorySvc,
    ctx: Auth,
    library: MemoryLibrary = Query("personal"),
) -> Any:
    """Use this object as the primary identity for another object in the same audience."""
    return await service.merge_objects(ctx, library=library, target_id=object_id, data=data)


@router.delete("/objects/{object_id}/merges/{merge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def undo_memory_object_merge(
    object_id: UUID,
    merge_id: UUID,
    service: MemorySvc,
    ctx: Auth,
    library: MemoryLibrary = Query("personal"),
) -> None:
    """Restore each object with the claims filed under its original identity."""
    await service.undo_object_merge(ctx, library=library, target_id=object_id, merge_id=merge_id)


@router.get("/objects/{object_id}", response_model=MemoryObjectTimeline)
async def memory_object_timeline(
    object_id: UUID,
    service: MemorySvc,
    ctx: Auth,
    library: MemoryLibrary = Query("personal"),
    as_of: AwareDatetime | None = Query(None),
    known_at: AwareDatetime | None = Query(None),
    cursor: UUID | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
) -> Any:
    """Read an object's history or the claims valid at an effective and knowledge time."""
    return await service.object_timeline(
        ctx,
        library=library,
        object_id=object_id,
        as_of=as_of,
        known_at=known_at,
        cursor=cursor,
        limit=limit,
    )


@router.post("/claims/mine/{claim_id}/share", response_model=MemoryClaimRead)
async def publish_memory_claim(
    claim_id: UUID, data: MemoryClaimShare, service: MemorySvc, ctx: Auth
) -> Any:
    """Publish an explicitly confirmed personal claim to an authorized audience."""
    return await service.publish_claim(ctx, claim_id, data)


@router.get("/claims/shared", response_model=MemoryClaimList)
async def shared_memory_claims(
    service: MemorySvc,
    ctx: Auth,
    q: str = Query("", max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    disputed: bool = False,
) -> Any:
    """Read current claims shared with this member's organization or groups."""
    return await service.shared_claims(ctx, q=q, skip=skip, limit=limit, disputed=disputed)


@router.get("/claims/shared/{claim_id}", response_model=MemoryClaimDetail)
async def shared_memory_claim(
    claim_id: UUID,
    service: MemorySvc,
    ctx: Auth,
) -> Any:
    """Read one shared claim and any ancestry available to the member."""
    return await service.shared_claim_detail(ctx, claim_id)


@router.post("/claims/shared/{claim_id}/resolve", response_model=MemoryClaimRead)
async def resolve_shared_memory_conflict(
    claim_id: UUID,
    data: MemoryConflictResolve,
    service: MemorySvc,
    ctx: Auth,
) -> Any:
    """Confirm the chosen value in a shared object's current dispute."""
    return await service.resolve_shared_conflict(ctx, claim_id, data)


@router.get("/notes/shared", response_model=SharedMemoryNotePage)
async def shared_memory_notes(
    service: MemorySvc,
    ctx: Auth,
    cursor: UUID | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
) -> Any:
    """Read notes explicitly published to this member's organization or groups."""
    return await service.shared_notes(ctx, cursor=cursor, limit=limit)


@router.post("/mine/{note_id}/share", response_model=SharedMemoryNoteRead)
async def publish_memory_note(
    note_id: UUID, data: MemoryNoteShare, service: MemorySvc, ctx: Auth
) -> Any:
    """Publish an explicitly reviewed version of a personal note."""
    return await service.publish_note(ctx, note_id, data)


@router.get("/mine", response_model=MemoryNoteList)
async def my_memory(
    service: MemorySvc,
    ctx: Auth,
    skip: int = Query(0, ge=0, description="Notes to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max notes to return"),
    q: str = Query("", max_length=200, description="Search all owned notes before pagination"),
) -> Any:
    """What the agents in this organization have written down about the caller.

    Across agents, because the question somebody asks of their own memory is
    "what is written down about me here", not "what does this one agent think".
    Suppressed notes are included and marked: they are the caller's own, and a
    view that hid them would be one they could not restore anything from.
    """
    return await service.mine(ctx, skip=skip, limit=limit, q=q)


@router.patch("/mine/{file_id}", response_model=MemoryNoteRead)
async def set_my_note_active(
    file_id: UUID,
    data: MemoryNoteUpdate,
    service: MemorySvc,
    ctx: Auth,
) -> Any:
    """Suppress one of the caller's own notes, or restore it.

    A suppressed note is not listed, not read and not editable by any tool, so it
    stops reaching the model without being destroyed - the middle answer between
    living with a note and erasing everything.
    """
    return await service.set_active(ctx, file_id, active=data.active)


@router.patch("/mine/{file_id}/auto-update", response_model=MemoryNoteRead)
async def set_my_note_auto_update(
    file_id: UUID, data: MemoryNoteAutoUpdate, service: MemorySvc, ctx: Auth
) -> Any:
    """Allow or stop maintenance updates for a note in the caller's own store."""
    return await service.set_note_auto_update(ctx, file_id, data)


@router.get("/mine/{file_id}/revisions", response_model=MemoryNoteRevisionList)
async def list_my_note_revisions(
    file_id: UUID,
    service: MemorySvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(5, ge=1, le=20),
) -> Any:
    """Read previous bodies of a note in the caller's own store."""
    return await service.note_revisions(ctx, file_id, skip=skip, limit=limit)


@router.post("/mine/{file_id}/revisions/{revision_id}/restore", response_model=MemoryNoteRead)
async def restore_my_note_revision(
    file_id: UUID, revision_id: UUID, data: MemoryNoteRestore, service: MemorySvc, ctx: Auth
) -> Any:
    """Restore an earlier body, preserving the one being replaced."""
    return await service.restore_note_revision(ctx, file_id, revision_id, data)


@router.patch("/mine/{file_id}/content", response_model=MemoryNoteRead)
async def edit_my_note(file_id: UUID, data: MemoryNoteEdit, service: MemorySvc, ctx: Auth) -> Any:
    """Correct a personal note without changing suppression or agent provenance."""
    return await service.edit_note(ctx, file_id, data)


@router.delete("/mine/{file_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_my_note(file_id: UUID, service: MemorySvc, ctx: Auth) -> None:
    """Delete one of the caller's own notes outright."""
    await service.delete_note(ctx, file_id)


@router.get("/claims/mine", response_model=MemoryClaimList)
async def my_claims(
    service: MemorySvc,
    ctx: Auth,
    skip: int = Query(0, ge=0, description="Claims to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max claims to return"),
    history: bool = Query(False, description="Include superseded, merged and retracted claims"),
    q: str = Query(
        "",
        max_length=200,
        description="Search statements, topics and agent names before pagination",
    ),
    kind: Literal["fact", "preference", "decision"] | None = Query(None),
    scope: Literal["profile", "agent"] | None = Query(None),
) -> Any:
    """The facts, preferences and decisions recorded about the caller, with their source.

    Current claims by default; `history` adds what they replaced. Always the caller's
    own: no permission to ask for, and nobody else's through this route.
    """
    return await service.my_claims(
        ctx,
        skip=skip,
        limit=limit,
        history=history,
        q=q,
        kind=kind,
        scope=scope,
    )


@router.get("/claims/mine/{claim_id}", response_model=MemoryClaimDetail)
async def my_claim(claim_id: UUID, service: MemorySvc, ctx: Auth) -> Any:
    """One of the caller's claims with the claims it was drawn from and the one it replaced."""
    return await service.claim_detail(ctx, claim_id)


@router.post(
    "/claims/mine/{claim_id}/improve-case",
    response_model=DatasetCaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def reviewed_improve_case(
    claim_id: UUID, data: ImproveCaseReview, service: MemorySvc, ctx: Auth
) -> Any:
    """Add a personally reviewed decision episode to a dataset the caller may edit."""
    return await service.improve_case(ctx, claim_id, data)


@router.post("/claims/mine/{claim_id}/correct", response_model=MemoryClaimRead)
async def correct_my_claim(
    claim_id: UUID, data: MemoryClaimCorrect, service: MemorySvc, ctx: Auth
) -> Any:
    """Correct a claim in the caller's own words; the corrected claim stays in its history."""
    return await service.correct_claim(ctx, claim_id, data)


@router.post("/claims/mine/{claim_id}/retract", response_model=MemoryClaimRead)
async def retract_my_claim(claim_id: UUID, service: MemorySvc, ctx: Auth) -> Any:
    """Take a claim out of use. It and everything it came from stay in the history."""
    return await service.retract_claim(ctx, claim_id)


@router.get("/person/{user_id}", response_model=MemoryNoteList)
async def inspect_person_memory(
    user_id: UUID,
    service: MemorySvc,
    ctx: Auth,
    organization_id: UUID = Query(description="The tenant whose store to read"),
    reason: str | None = Query(None, description="Why this read is being made, for the trail"),
    skip: int = Query(0, ge=0, description="Notes to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max notes to return"),
) -> Any:
    """One named person's notes in one named tenant - a deployment admin only.

    The tenant is a parameter rather than the caller's active organization: an
    app admin acts across tenants, and a read that silently used whichever
    organization they had selected would be a read nobody could audit properly.

    Paged like the self-service listing, and for a sharper reason: an inspection
    that could only ever see the first fifty notes of a store holding more is an
    inspection that cannot answer a subject-access request.
    """
    return await service.for_person(
        ctx, organization_id, user_id, skip=skip, limit=limit, reason=reason
    )


@router.delete("/person/{user_id}", response_model=MemoryErasureResult)
async def forget_person(user_id: UUID, service: MemorySvc, ctx: Auth) -> Any:
    """Forget everything every agent in this organization knows about one person.

    Answers with what was removed rather than 204, so a caller can say how much
    of "forgotten" actually happened.
    """
    return await service.forget_person(ctx, user_id)


@router.delete("", response_model=MemoryErasureResult)
async def clear_agent_memory(
    service: MemorySvc,
    ctx: Auth,
    agent_id: UUID = Query(description="The agent whose notes to clear"),
) -> Any:
    """Delete every note one agent holds, in every store - the danger zone.

    A memory store nobody can clear is a liability (#788).
    """
    return await service.clear_agent(ctx, agent_id)
