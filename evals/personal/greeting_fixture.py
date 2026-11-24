"""Controlled task reads for greeting policy evals, never writes to a user's boards.

The production MCP route, authentication and tool schema still execute. Only the
selected eval subject's task-read results are substituted for these cases; this
measures model behavior, not database authorization or task persistence.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid4

from app.core.permissions import AuthContext
from app.schemas.task import TaskBoardRead, TaskList, TaskRead
from app.services.tasks import TaskService

BoardState = Literal["absent", "empty", "priorities"]
GREETING_STATES: dict[str, BoardState] = {
    "natural-hello": "absent",
    "hello-empty-board": "empty",
    "hello-priorities": "priorities",
    "hello-no-tools": "absent",
    "hello-repeat": "absent",
    "hello-shared-channel": "absent",
}
TABLE_ID = UUID("a0000099-0000-4000-8000-000000000099")


@contextmanager
def greeting_task_reads(ctx: AuthContext, state: BoardState) -> Iterator[None]:
    """Replace reads only for this subject/tenant; all other reads use the real service."""
    original_boards = TaskService.boards
    original_tasks = TaskService.list_tasks
    board_id = uuid4()
    now = datetime.now(UTC)

    def matches(candidate: AuthContext) -> bool:
        return candidate.user_id == ctx.user_id and candidate.organization_id == ctx.organization_id

    async def boards(service: TaskService, candidate: AuthContext) -> list[TaskBoardRead]:
        if not matches(candidate):
            return await original_boards(service, candidate)
        if state == "absent":
            return []
        return [
            TaskBoardRead(
                id=board_id,
                scope_kind="private",
                scope_id=ctx.subject_id,
                scope_name="Your private tasks",
                table_id=TABLE_ID,
                can_edit=True,
            )
        ]

    async def tasks(
        service: TaskService,
        candidate: AuthContext,
        table_id: UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> TaskList:
        if not matches(candidate) or table_id != TABLE_ID or state == "absent":
            return await original_tasks(service, candidate, table_id, skip=skip, limit=limit)
        rows = (
            []
            if state == "empty"
            else [
                TaskRead(
                    id=uuid4(),
                    table_id=TABLE_ID,
                    board_id=board_id,
                    scope="private",
                    scope_id=ctx.subject_id,
                    title=title,
                    next_actor="user",
                    revision=1,
                    conversation_id=None,
                    outcome_id=None,
                    created_at=now,
                    due_at=now + timedelta(hours=hours),
                )
                for title, hours in [("ORION budget review", 2), ("LYRA demo rehearsal", 24)]
            ]
        )
        return TaskList(items=rows[skip : skip + limit], has_more=skip + limit < len(rows))

    with (
        patch.object(TaskService, "boards", boards),
        patch.object(TaskService, "list_tasks", tasks),
    ):
        yield
