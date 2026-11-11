"""Durable tasks: the same records displayed in Tables and linked from chats."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Auth, DurableTaskSvc, key_needs, require
from app.api.public_api import PUBLIC
from app.core.permissions import Perm
from app.schemas.task import BoardEnsure, TaskBoardRead, TaskCreate, TaskList, TaskRead, TaskUpdate

router = APIRouter(dependencies=[PUBLIC, Depends(key_needs(Perm.TABLES_VIEW))])


@router.get(
    "/boards", response_model=list[TaskBoardRead], dependencies=[Depends(require(Perm.TABLES_VIEW))]
)
async def list_boards(ctx: Auth, service: DurableTaskSvc) -> Any:
    """List accessible boards without creating empty tables."""
    return await service.boards(ctx)


@router.post("/boards", response_model=TaskBoardRead)
async def ensure_board(data: BoardEnsure, ctx: Auth, service: DurableTaskSvc) -> Any:
    """Create a scope's board on first use, or return the existing one."""
    return await service.open_board(ctx, data)


@router.get("", response_model=TaskList)
async def list_tasks(
    ctx: Auth,
    service: DurableTaskSvc,
    table_id: UUID,
    skip: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=50, ge=1, le=100),
) -> Any:
    """Read a page of tasks through its board's live audience."""
    return await service.list_tasks(ctx, table_id, skip=skip, limit=limit)


@router.post("", response_model=TaskRead, status_code=201)
async def create_task(data: TaskCreate, ctx: Auth, service: DurableTaskSvc) -> Any:
    """Persist a commitment; an assigned agent runs once at Start at or immediately."""
    return await service.create(ctx, data)


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: UUID, ctx: Auth, service: DurableTaskSvc) -> Any:
    """Describe one task and the working chat its caller may open."""
    return await service.get(ctx, task_id)


@router.put("/{task_id}", response_model=TaskRead)
async def update_task(task_id: UUID, data: TaskUpdate, ctx: Auth, service: DurableTaskSvc) -> Any:
    """Replace task fields at an expected revision; stale edits return conflict."""
    return await service.update(ctx, task_id, data)
