"""Context-file routes - an organization's standing context for its agents.

A context file is content: an operator edits the glossary here and every agent
bound to it is current on the next run, with no deploy.

Routes acting on the collection carry a `require(...)` gate; routes acting on
one file deliberately do not, and delegate to `ContextService` instead. A
role-level gate cannot see the grants on a row, so it would refuse a viewer who
was explicitly given edit on a single file - the exact case sharing exists for.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, ContextSvc, require
from app.core.permissions import Perm
from app.repositories.context import ContextSort
from app.schemas.context import (
    ContextFileCreate,
    ContextFileList,
    ContextFileRead,
    ContextFileUpdate,
)

router = APIRouter()


@router.get("", response_model=ContextFileList, dependencies=[Depends(require(Perm.CONTEXT_VIEW))])
async def list_context_files(
    service: ContextSvc,
    ctx: Auth,
    q: str | None = Query(None, max_length=100, description="Match on name or description"),
    sort: ContextSort = Query("name", description="`name` A-Z, or `updated` newest change first"),
    shared_with_me: bool = Query(
        False, description="Only what was shared with the caller - never their own rows"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Names, modes and sizes - the picker, not the bodies."""
    return await service.list_readable(
        ctx,
        shared_with_me=shared_with_me,
        search=q,
        sort=sort,
        skip=skip,
        limit=limit,
    )


@router.post(
    "",
    response_model=ContextFileRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.CONTEXT_EDIT))],
)
async def create_context_file(data: ContextFileCreate, service: ContextSvc, ctx: Auth) -> Any:
    return await service.create(
        ctx,
        name=data.name,
        description=data.description,
        content=data.content,
        content_format=data.format,
        mode=data.mode,
    )


@router.get("/{context_id}", response_model=ContextFileRead)
async def get_context_file(context_id: UUID, service: ContextSvc, ctx: Auth) -> Any:
    return await service.get(ctx, context_id)


@router.patch("/{context_id}", response_model=ContextFileRead)
async def update_context_file(
    context_id: UUID, data: ContextFileUpdate, service: ContextSvc, ctx: Auth
) -> Any:
    """Edit a context file. Every agent bound to it is current on the next run."""
    return await service.update(ctx, context_id, data)


@router.delete(
    "/{context_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_context_file(context_id: UUID, service: ContextSvc, ctx: Auth) -> None:
    await service.delete(ctx, context_id)
