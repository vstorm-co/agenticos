"""Memory-file routes - operator management of an agent's own memory.

Every route here acts on the memory of *one* agent, so none carries a
`require(...)` gate: a role-level gate cannot see a grant on a specific agent, so
it would refuse a viewer who was explicitly given edit on that agent - the case
sharing exists for. Access is decided per agent inside `MemoryService`
(`resolve_access` against the parent agent), and a denial is a 404, because
whether an agent's memory exists is itself something the caller may not learn.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import Auth, MemorySvc
from app.repositories.memory import MemorySort
from app.schemas.memory import (
    AgentMemoryFactList,
    AgentMemoryFactRead,
    AgentMemoryFileCreate,
    AgentMemoryFileList,
    AgentMemoryFileRead,
    AgentMemoryFileUpdate,
)

router = APIRouter()


@router.get("/files", response_model=AgentMemoryFileList)
async def list_memory_files(
    service: MemorySvc,
    ctx: Auth,
    agent_id: UUID = Query(description="The agent whose memory to list"),
    partition: str = Query(
        "all",
        description="`all`, `shared`, `per_user`, or an end-user key to confine the listing",
    ),
    q: str | None = Query(None, max_length=100, description="Match on name or description"),
    sort: MemorySort = Query("name", description="`name` A-Z, or `updated` newest change first"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Names, kinds, origins and sizes - the index, not the bodies."""
    return await service.list_files(
        ctx,
        agent_id=agent_id,
        scope_key=None if partition in ("all", "shared", "per_user") else partition,
        all_partitions=partition == "all",
        scoped_only=partition == "per_user",
        search=q,
        sort=sort,
        skip=skip,
        limit=limit,
    )


@router.post("/files", response_model=AgentMemoryFileRead, status_code=status.HTTP_201_CREATED)
async def create_memory_file(data: AgentMemoryFileCreate, service: MemorySvc, ctx: Auth) -> Any:
    """Create an operator-authored (trusted) memory file for an agent."""
    return await service.create(ctx, data)


@router.get("/files/{file_id}", response_model=AgentMemoryFileRead)
async def get_memory_file(file_id: UUID, service: MemorySvc, ctx: Auth) -> Any:
    return await service.get(ctx, file_id)


@router.patch("/files/{file_id}", response_model=AgentMemoryFileRead)
async def update_memory_file(
    file_id: UUID, data: AgentMemoryFileUpdate, service: MemorySvc, ctx: Auth
) -> Any:
    """Edit a memory file. An agent-authored file stays agent-authored - see `promote`."""
    return await service.update(ctx, file_id, data)


@router.post("/files/{file_id}/promote", response_model=AgentMemoryFileRead)
async def promote_memory_file(file_id: UUID, service: MemorySvc, ctx: Auth) -> Any:
    """Mark an agent-authored file operator-trusted; v1 shows the trust as a badge,
    it is not yet spliced into the prompt."""
    return await service.promote(ctx, file_id)


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_memory_file(file_id: UUID, service: MemorySvc, ctx: Auth) -> None:
    await service.delete(ctx, file_id)


@router.get("/facts", response_model=AgentMemoryFactList)
async def list_memory_facts(
    service: MemorySvc,
    ctx: Auth,
    agent_id: UUID = Query(description="The agent whose facts to list"),
    partition: str = Query(
        "all",
        description="`all`, `shared`, `per_user`, or an end-user key to confine the listing",
    ),
    q: str | None = Query(None, max_length=100, description="Substring match on the fact text"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The agent's remembered facts, newest first. Search is a substring match,
    not semantic - a semantic query would embed off the run's ledger."""
    return await service.list_facts(
        ctx,
        agent_id=agent_id,
        scope_key=None if partition in ("all", "shared", "per_user") else partition,
        all_partitions=partition == "all",
        scoped_only=partition == "per_user",
        search=q,
        skip=skip,
        limit=limit,
    )


@router.get("/facts/{fact_id}", response_model=AgentMemoryFactRead)
async def get_memory_fact(fact_id: UUID, service: MemorySvc, ctx: Auth) -> Any:
    return await service.get_fact(ctx, fact_id)


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_memory_fact(fact_id: UUID, service: MemorySvc, ctx: Auth) -> None:
    """Forget a fact. Operators do not create or edit facts - only the agent does,
    at runtime - but clearing one is a management action."""
    await service.delete_fact(ctx, fact_id)


@router.delete("/facts", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def clear_memory_facts(
    service: MemorySvc,
    ctx: Auth,
    agent_id: UUID = Query(description="The agent whose facts to clear"),
) -> None:
    """Forget every fact for an agent, in every partition, leaving its files -
    what the agent has learned, reset without discarding operator-authored files."""
    await service.clear_facts(ctx, agent_id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def clear_memory(
    service: MemorySvc,
    ctx: Auth,
    agent_id: UUID = Query(description="The agent whose memory to clear"),
) -> None:
    """Delete every file and fact for an agent, in every partition - the danger
    zone. A memory store nobody can clear is a liability (#788)."""
    await service.clear(ctx, agent_id)
