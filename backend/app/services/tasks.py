"""Durable tasks backed by scoped Virtual Tables, with transactional lifecycle hooks."""

from contextvars import ContextVar
from uuid import UUID, uuid5

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.task_board import TaskBoard, TaskLink
from app.db.models.virtual_table import VirtualTableRecord
from app.repositories import (
    conversation_repo,
    group_repo,
    member_repo,
    project_repo,
    user_repo,
    virtual_table_repo,
)
from app.repositories import task as task_repo
from app.schemas.table_view import TableViewConfig, TableViewCreate
from app.schemas.task import (
    BoardEnsure,
    TaskBoardRead,
    TaskCreate,
    TaskFields,
    TaskList,
    TaskRead,
    TaskUpdate,
)
from app.schemas.virtual_table import (
    ColumnDef,
    RecordCreate,
    RecordFilter,
    RecordQuery,
    RecordSource,
    RecordUpdate,
    TableCreate,
)
from app.services.task_access import board_allows, scope_allows
from app.services.task_columns import STATUSES, from_cells, task_columns, to_cells
from app.services.virtual_tables import TableViewService, VirtualTableService

_SOURCE_FINDING: ContextVar[bool] = ContextVar("task_source_finding", default=False)


class TaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tables = VirtualTableService(db)

    async def require_no_agent_execution(self, ctx: AuthContext, agent_id: UUID) -> None:
        """Keep deleting an agent from silently discarding a task's scheduled work."""
        if await task_repo.has_agent_execution(self.db, ctx.organization_id, agent_id):
            raise BadRequestError(
                message="This agent still has scheduled task work. Reassign, complete or cancel those tasks before deleting the agent.",
                details={"agent_id": agent_id},
            )

    async def purge_scope(
        self, kind: str, scope_id: UUID, *, organization_id: UUID | None = None
    ) -> None:
        """Remove managed task data and queued work with the scope that authorized it."""
        from app.repositories import resource_grant_repo
        from app.services.task_execution import TaskExecution

        if organization_id is not None:
            await hold_subject(
                self.db, LockScope.TASK_BOARD, uuid5(organization_id, f"{kind}:{scope_id}")
            )
        for board in await task_repo.in_scope(self.db, kind, scope_id, organization_id):
            if organization_id is None:
                await hold_subject(
                    self.db,
                    LockScope.TASK_BOARD,
                    uuid5(board.organization_id, f"{kind}:{scope_id}"),
                )
            table = await virtual_table_repo.get_table(
                self.db, board.table_id, organization_id=board.organization_id, for_update=True
            )
            if table is None:
                continue
            await TaskExecution(self.db).purge_board(board)
            await resource_grant_repo.delete_for_resource(
                self.db,
                organization_id=board.organization_id,
                resource_type="table",
                resource_id=board.table_id,
            )
            await task_repo.purge_table(self.db, board)

    async def ensure_board(self, ctx: AuthContext, data: BoardEnsure) -> TaskBoard:
        scope_id = data.scope_id
        if data.scope == "private":
            scope_id = scope_id or ctx.user_id
        elif data.scope == "organization":
            scope_id = scope_id or ctx.organization_id
        if scope_id is None or not await scope_allows(
            self.db, ctx, data.scope, scope_id, edit=True
        ):
            raise NotFoundError(message="Task scope not found")
        if data.scope == "private":
            await hold_subject(self.db, LockScope.PERSONAL_DATA_PER_USER, scope_id)
            if await user_repo.get_by_id(self.db, scope_id) is None:
                raise NotFoundError(message="Task scope not found")
        # The binding, not a person's idempotency receipt: two project members
        # opening Tasks together must get the same board.
        await hold_subject(
            self.db, LockScope.TASK_BOARD, uuid5(ctx.organization_id, f"{data.scope}:{scope_id}")
        )
        if not await scope_allows(self.db, ctx, data.scope, scope_id, edit=True):
            raise NotFoundError(message="Task scope not found")
        board = await task_repo.for_scope(self.db, ctx.organization_id, data.scope, scope_id)
        if board is not None:
            return board
        scope_name = await self._scope_name(ctx, data.scope, scope_id)
        table = await self.tables.create_table(
            ctx,
            TableCreate(
                name=f"Tasks · {(scope_name or data.scope)[:32]} · {scope_id.hex[:12]}",
                description="Shared task state for chat, Tables and Inbox. Start at launches work; Due at is the deadline.",
                visibility="private",
                columns=task_columns(),
            ),
        )
        column_ids = {
            name: str(column.id)
            for name, column in zip(
                (
                    "title",
                    "status",
                    "description",
                    "assignee_user_id",
                    "assignee_agent_id",
                    "start_at",
                    "due_at",
                    "next_actor",
                ),
                table.columns,
                strict=True,
            )
        }
        # Column order follows the task contract, independently of displayed labels.
        board = await task_repo.add_board(
            self.db,
            TaskBoard(
                organization_id=ctx.organization_id,
                scope_kind=data.scope,
                scope_id=scope_id,
                table_id=table.id,
                column_ids=column_ids,
                status_ids={
                    **{
                        status: str(option.id)
                        for status, option in zip(STATUSES, table.columns[1].options, strict=True)
                    },
                    **{
                        f"actor:{actor}": str(option.id)
                        for actor, option in zip(
                            ("user", "agent"), table.columns[-1].options, strict=True
                        )
                    },
                },
            ),
        )
        default_view = await TableViewService(self.db).create_view(
            ctx,
            table.id,
            TableViewCreate(
                name="Board",
                kind="kanban",
                visibility="shared",
                config=TableViewConfig(group_by=table.columns[1].id),
            ),
        )
        # The board row already exists here, and the person creating it need not be one
        # who may change it later, so the default view is set as part of creating it.
        created = await virtual_table_repo.get_table(
            self.db, table.id, organization_id=ctx.organization_id, for_update=True
        )
        assert created is not None
        await virtual_table_repo.update_table(
            self.db, table=created, update_data={"default_view_id": default_view.id}
        )
        views = TableViewService(self.db)
        await views.create_view(
            ctx, table.id, TableViewCreate(name="All tasks", kind="table", visibility="shared")
        )
        await views.create_view(
            ctx,
            table.id,
            TableViewCreate(
                name="Open tasks",
                kind="table",
                visibility="shared",
                config=TableViewConfig(
                    filters=[
                        RecordFilter(
                            column_id=table.columns[1].id, op="ne", value=board.status_ids[status]
                        )
                        for status in ("done", "cancelled")
                    ]
                ),
            ),
        )
        await views.create_view(
            ctx,
            table.id,
            TableViewCreate(
                name="Blocked",
                kind="list",
                visibility="shared",
                config=TableViewConfig(
                    filters=[
                        RecordFilter(
                            column_id=table.columns[1].id,
                            op="eq",
                            value=board.status_ids["blocked"],
                        )
                    ]
                ),
            ),
        )
        for name, field, op, value in (
            ("Waiting for review", "status", "eq", board.status_ids["waiting_for_user"]),
            ("Planned", "status", "eq", board.status_ids["planned"]),
            ("Agent tasks", "next_actor", "eq", board.status_ids["actor:agent"]),
        ):
            await views.create_view(
                ctx,
                table.id,
                TableViewCreate(
                    name=name,
                    kind="table",
                    visibility="shared",
                    config=TableViewConfig(
                        filters=[
                            RecordFilter.model_validate(
                                {"column_id": board.column_ids[field], "op": op, "value": value}
                            )
                        ]
                    ),
                ),
            )
        return board

    async def open_board(self, ctx: AuthContext, data: BoardEnsure) -> TaskBoardRead:
        """`ensure_board`, answered the way `boards` lists it."""
        return await self._board_read(ctx, await self.ensure_board(ctx, data))

    async def boards(self, ctx: AuthContext) -> list[TaskBoardRead]:
        return [
            await self._board_read(ctx, board)
            for board in await task_repo.boards(self.db, ctx.organization_id)
            if await board_allows(self.db, ctx, board, Perm.TABLES_VIEW)
        ]

    async def _board_read(self, ctx: AuthContext, board: TaskBoard) -> TaskBoardRead:
        table = await virtual_table_repo.get_table(
            self.db, board.table_id, organization_id=ctx.organization_id
        )
        editable = (
            table is not None
            and table.archived_at is None
            and await board_allows(self.db, ctx, board, Perm.TABLES_EDIT)
        )
        return TaskBoardRead.model_validate(board).model_copy(
            update={
                "scope_name": await self._scope_name(ctx, board.scope_kind, board.scope_id),
                "can_edit": editable,
            }
        )

    async def _scope_name(self, ctx: AuthContext, kind: str, scope_id: UUID) -> str | None:
        if kind == "project":
            project = await project_repo.get(self.db, scope_id, organization_id=ctx.organization_id)
            return project.name if project else None
        if kind == "group":
            group = await group_repo.get(
                self.db, group_id=scope_id, organization_id=ctx.organization_id
            )
            return group.name if group else None
        if kind == "private":
            user = await user_repo.get_by_id(self.db, scope_id)
            return user.full_name if user else None
        return None

    async def create(self, ctx: AuthContext, data: TaskCreate) -> TaskRead:
        board = await self.ensure_board(ctx, BoardEnsure(scope=data.scope, scope_id=data.scope_id))
        conversation_id = await self._conversation(ctx, board, data.conversation_id)
        fields = TaskFields.model_validate(data.model_dump(include=set(TaskFields.model_fields)))
        if fields.assignee_user_id is None:
            fields.assignee_user_id = ctx.user_id
        if data.external_id is not None:
            existing = await virtual_table_repo.get_record_by_external_id(
                self.db,
                data.external_id,
                table_id=board.table_id,
                organization_id=ctx.organization_id,
                for_update=True,
            )
            if existing is not None:
                return await self.get(ctx, existing.id)
        initial = fields.model_copy(
            update={
                "assignee_agent_id": None,
                "start_at": None,
                "next_actor": "user",
                "status": "planned",
            }
        )
        written = await self.tables.create_record(
            ctx,
            board.table_id,
            RecordCreate(external_id=data.external_id, values=to_cells(board, initial)),
        )
        link = await task_repo.link(self.db, written.record.id)
        if link is None:
            raise RuntimeError("Task record was created without its lifecycle binding")
        link.conversation_id = conversation_id
        await task_repo.flush(self.db)
        if initial != fields:
            await self.tables.update_record(
                ctx,
                board.table_id,
                written.record.id,
                RecordUpdate(
                    values=to_cells(board, fields), expected_revision=written.record.revision
                ),
            )
        return await self.get(ctx, written.record.id)

    async def get(self, ctx: AuthContext, task_id: UUID) -> TaskRead:
        record = await task_repo.record(self.db, task_id, ctx.organization_id)
        if record is None:
            raise NotFoundError(message="Task not found")
        board = await task_repo.for_table(self.db, record.table_id, ctx.organization_id)
        if board is None or not await board_allows(self.db, ctx, board, Perm.TABLES_VIEW):
            raise NotFoundError(message="Task not found")
        link = await task_repo.link(self.db, record.id)
        fields = from_cells(board, record.values)
        # A shared task never exposes a private working chat or private Inbox case.
        conversation_id = None
        outcome_id = None
        if link is not None and link.creator_user_id == ctx.user_id:
            conversation_id = link.conversation_id
            outcome_id = link.outcome_id
        return TaskRead.model_validate(
            {
                **fields.model_dump(),
                "id": record.id,
                "table_id": board.table_id,
                "board_id": board.id,
                "scope": board.scope_kind,
                "scope_id": board.scope_id,
                "revision": record.revision,
                "conversation_id": conversation_id,
                "outcome_id": outcome_id,
                "created_at": record.created_at,
            }
        )

    async def assignee_options(self, ctx: AuthContext, table_id: UUID) -> list[RecordSource] | None:
        """Managed-task people must satisfy the same live scope check as a write."""
        from app.services.access import member_context

        await self.tables.describe_table(ctx, table_id)
        board = await task_repo.for_table(self.db, table_id, ctx.organization_id)
        if board is None:
            return None
        if not await board_allows(self.db, ctx, board, Perm.TABLES_EDIT):
            raise NotFoundError(message="Task board not found")
        options: list[RecordSource] = []
        skip = 0
        while True:
            members = await member_repo.list_for_org(
                self.db, ctx.organization_id, skip=skip, limit=100
            )
            for member, email, name, _avatar_url, avatar_color in members:
                if board.scope_kind == "private" and member.user_id != board.scope_id:
                    continue
                person = await member_context(
                    self.db, organization_id=ctx.organization_id, user_id=member.user_id
                )
                if person is not None and await board_allows(
                    self.db, person, board, Perm.TABLES_EDIT
                ):
                    options.append(
                        RecordSource(
                            kind="user",
                            id=member.user_id,
                            name=name or email,
                            avatar_color=avatar_color,
                        )
                    )
            if len(members) < 100:
                break
            skip += len(members)
        return options

    async def list_tasks(
        self, ctx: AuthContext, table_id: UUID, *, skip: int = 0, limit: int = 50
    ) -> TaskList:
        board = await task_repo.for_table(self.db, table_id, ctx.organization_id)
        if board is None:
            raise NotFoundError(message="Task board not found")
        records = await self.tables.list_records(ctx, table_id, RecordQuery(skip=skip, limit=limit))
        return TaskList(
            items=[await self.get(ctx, row.id) for row in records.items], has_more=records.has_more
        )

    async def update(self, ctx: AuthContext, task_id: UUID, data: TaskUpdate) -> TaskRead:
        existing = await self.get(ctx, task_id)
        board = await task_repo.for_table(self.db, existing.table_id, ctx.organization_id)
        if board is None:
            raise NotFoundError(message="Task board not found")
        fields = TaskFields.model_validate(data.model_dump(include=set(TaskFields.model_fields)))
        before = to_cells(
            board,
            TaskFields.model_validate(existing.model_dump(include=set(TaskFields.model_fields))),
        )
        changed = {
            key: value for key, value in to_cells(board, fields).items() if before.get(key) != value
        }
        await self.tables.update_record(
            ctx,
            board.table_id,
            task_id,
            RecordUpdate(values=changed, expected_revision=data.expected_revision),
        )
        return await self.get(ctx, task_id)

    async def finding(
        self,
        ctx: AuthContext,
        *,
        outcome_id: UUID,
        conversation_id: UUID,
        title: str,
        description: str,
        agent_id: UUID | None = None,
    ) -> TaskRead:
        token = _SOURCE_FINDING.set(True)
        try:
            return await self._finding(
                ctx,
                outcome_id=outcome_id,
                conversation_id=conversation_id,
                title=title,
                description=description,
                agent_id=agent_id,
            )
        finally:
            _SOURCE_FINDING.reset(token)

    async def _finding(
        self,
        ctx: AuthContext,
        *,
        outcome_id: UUID,
        conversation_id: UUID,
        title: str,
        description: str,
        agent_id: UUID | None = None,
    ) -> TaskRead:
        """One source case keeps its task identity across new source revisions."""
        task = await self.create(
            ctx,
            TaskCreate(
                title=title,
                description=description,
                status="waiting_for_user",
                next_actor="user",
                assignee_agent_id=agent_id,
                conversation_id=conversation_id,
                external_id=f"case:{outcome_id}",
            ),
        )
        link = await task_repo.link(self.db, task.id)
        if link is None:
            raise RuntimeError("Finding task has no binding")
        # The source publisher owns reopening and notifying its case revision.
        previous_case = link.outcome_id
        link.outcome_id = None
        await task_repo.flush(self.db)
        if previous_case is not None and previous_case != outcome_id:
            from app.services.outcome import OutcomeService

            await OutcomeService(self.db).resolve_task(
                previous_case, organization_id=ctx.organization_id
            )
        if (task.title, task.description, task.status) != (title, description, "waiting_for_user"):
            task = await self.update(
                ctx,
                task.id,
                TaskUpdate(
                    title=title,
                    description=description,
                    status="waiting_for_user",
                    assignee_user_id=ctx.user_id,
                    assignee_agent_id=agent_id,
                    next_actor="user",
                    expected_revision=task.revision,
                ),
            )
        link = await task_repo.link(self.db, task.id)
        if link is None:
            raise RuntimeError("Finding task has no binding")
        link.outcome_id = outcome_id
        link.conversation_id = conversation_id
        await task_repo.flush(self.db)
        return await self.get(ctx, task.id)

    async def _conversation(
        self, ctx: AuthContext, board: TaskBoard, requested: UUID | None
    ) -> UUID | None:
        conversation_id = requested or ctx.source_conversation_id
        if conversation_id is None:
            return None
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        if (
            conversation is None
            or conversation.organization_id != ctx.organization_id
            or conversation.user_id != ctx.user_id
            or conversation.is_archived
        ):
            raise NotFoundError(message="Working conversation not found")
        if ctx.source_conversation_id is not None and conversation_id != ctx.source_conversation_id:
            raise AuthorizationError(message="A chat can link tasks only to itself")
        if board.scope_kind == "project" and conversation.project_id != board.scope_id:
            if requested is None:
                # A personal chat may create project work, but is not that
                # project's shared working conversation. Let task execution open one.
                return None
            raise BadRequestError(message="Choose a conversation in the task's project")
        return conversation_id


class TaskLifecycle:
    """Called inside every generic record write, including Kanban, imports and MCP."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def changed(self, ctx: AuthContext, record: VirtualTableRecord) -> None:
        board = await task_repo.for_table(self.db, record.table_id, ctx.organization_id)
        if board is None:
            return
        try:
            fields = from_cells(board, record.values)
        except ValidationError as error:
            raise BadRequestError(
                message="Invalid task fields",
                details={"errors": error.errors(include_input=False, include_context=False)},
            ) from error
        link = await task_repo.link(self.db, record.id)
        if link is None:
            link = await task_repo.add_link(
                self.db,
                TaskLink(record_id=record.id, board_id=board.id, creator_user_id=ctx.user_id),
            )
        if fields.assignee_user_id is not None:
            from app.services.access import member_context

            reviewer = await member_context(
                self.db, organization_id=ctx.organization_id, user_id=fields.assignee_user_id
            )
            if reviewer is None or not await board_allows(
                self.db, reviewer, board, Perm.TABLES_EDIT
            ):
                raise BadRequestError(message="Choose a person who can access this task's scope")
        await self._schedule(ctx, board, record, link, fields)

    async def _schedule(
        self,
        ctx: AuthContext,
        board: TaskBoard,
        record: VirtualTableRecord,
        link: TaskLink,
        fields: TaskFields,
    ) -> None:
        # Scheduling and attention are part of the same transaction as the record.
        from app.services.task_execution import TaskExecution

        await TaskExecution(self.db).changed(
            ctx, board, record, link, fields, publish_attention=not _SOURCE_FINDING.get()
        )

    async def protect_schema(
        self, ctx: AuthContext, table_id: UUID, columns: list[ColumnDef]
    ) -> None:
        board = await task_repo.for_table(self.db, table_id, ctx.organization_id)
        if board is None:
            return
        by_id = {str(column.id): column for column in columns}
        for name, original in zip(
            (
                "title",
                "status",
                "description",
                "assignee_user_id",
                "assignee_agent_id",
                "start_at",
                "due_at",
                "next_actor",
            ),
            task_columns(),
            strict=True,
        ):
            column = by_id.get(board.column_ids[name])
            if (
                column is None
                or column.archived
                or column.type != original.type
                or column.nullable != original.nullable
            ):
                raise BadRequestError(
                    message="Task fields must retain their type and remain available",
                    details={"field": name},
                )
            if name == "status" and {board.status_ids[status] for status in STATUSES} != {
                str(option.id) for option in column.options if not option.archived
            }:
                raise BadRequestError(message="Task states cannot be removed or archived")
            if name == "next_actor" and {
                board.status_ids["actor:user"],
                board.status_ids["actor:agent"],
            } != {str(option.id) for option in column.options if not option.archived}:
                raise BadRequestError(message="The next-step choices must remain Person and Agent")
