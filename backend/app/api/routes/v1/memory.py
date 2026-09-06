"""Memory routes - erasure, and nothing else.

An agent's notes are written by the agent. There is no authoring surface here and
no listing: an operator paging through what an agent learned about a named
colleague is a surveillance affordance rather than a feature, and anything a
person wants an agent to know belongs in `context` (#1470).

Neither route carries a `require(...)` gate, for the two different reasons this
project distinguishes. Clearing one agent is a per-resource act, so a role gate
would refuse a viewer holding an explicit grant on that agent before
`resolve_access` could widen it. Forgetting a person is not an agent act at all -
it is somebody erasing themselves, or `MEMBERS_MANAGE` erasing a member - and the
service is where that is decided.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import Auth, MemorySvc
from app.schemas.memory import MemoryErasureResult

router = APIRouter()


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
