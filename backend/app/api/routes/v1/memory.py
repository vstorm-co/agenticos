"""Memory routes: what a person may see of their own, and what erasure removes.

An agent's notes are written by the agent, so there is still no authoring surface
here - anything a person wants an agent to *know* belongs in `context` (#1470).
What #1594 added is the reading half, and who may do it:

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

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import Auth, MemorySvc
from app.schemas.memory import (
    MemoryErasureResult,
    MemoryNoteList,
    MemoryNoteRead,
    MemoryNoteUpdate,
)

router = APIRouter()


@router.get("/mine", response_model=MemoryNoteList)
async def my_memory(
    service: MemorySvc,
    ctx: Auth,
    skip: int = Query(0, ge=0, description="Notes to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max notes to return"),
) -> Any:
    """What the agents in this organization have written down about the caller.

    Across agents, because the question somebody asks of their own memory is
    "what is written down about me here", not "what does this one agent think".
    Suppressed notes are included and marked: they are the caller's own, and a
    view that hid them would be one they could not restore anything from.
    """
    return await service.mine(ctx, skip=skip, limit=limit)


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


@router.delete("/mine/{file_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_my_note(file_id: UUID, service: MemorySvc, ctx: Auth) -> None:
    """Delete one of the caller's own notes outright."""
    await service.delete_note(ctx, file_id)


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

    Answers with what each half removed rather than 204, because the mem0 half is
    somebody else's service and a caller has to be able to say which parts of
    "forgotten" actually happened.
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
