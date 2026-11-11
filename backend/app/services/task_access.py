"""Managed boards inherit their audience live, including through generic table reads."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm, Scope
from app.db.models.task_board import TaskBoard
from app.repositories import group_repo, project_repo, resource_grant_repo
from app.repositories import task as task_repo


async def scope_allows(
    db: AsyncSession, ctx: AuthContext, kind: str, scope_id: UUID, *, edit: bool
) -> bool:
    if ctx.user_id is None or ctx.subject_is_publisher_fallback:
        return False
    if not ctx.key_allows(Perm.TABLES_EDIT if edit else Perm.TABLES_VIEW):
        return False
    if kind == "private":
        return scope_id == ctx.user_id and ctx.has(Perm.TABLES_EDIT if edit else Perm.TABLES_VIEW)
    if kind == "organization":
        return scope_id == ctx.organization_id and ctx.has(
            Perm.TABLES_EDIT if edit else Perm.TABLES_VIEW
        )
    if kind == "group":
        group = await group_repo.get(db, group_id=scope_id, organization_id=ctx.organization_id)
        if (
            group is None
            or await group_repo.get_member(db, group_id=scope_id, user_id=ctx.user_id) is None
        ):
            return False
        return not edit or await _may_edit_table(db, ctx, kind, scope_id)
    if kind == "project":
        from app.services.access import PROJECT, resolve_access

        project = await project_repo.get(db, scope_id, organization_id=ctx.organization_id)
        return (
            project is not None
            and (not edit or await _may_edit_table(db, ctx, kind, scope_id))
            and await resolve_access(
                db,
                ctx,
                project,
                Perm.PROJECTS_USE if edit else Perm.PROJECTS_VIEW,
                resource_type=PROJECT,
            )
        )
    return False


async def _may_edit_table(db: AsyncSession, ctx: AuthContext, kind: str, scope_id: UUID) -> bool:
    if ctx.has(Perm.TABLES_EDIT):
        return True
    board = await task_repo.for_scope(db, ctx.organization_id, kind, scope_id)
    if board is None or ctx.user_id is None:
        return False
    from app.db.models.resource_grant import GRANT_ORDER, GrantLevel

    granted = await resource_grant_repo.get_level(
        db,
        organization_id=ctx.organization_id,
        subject_user_id=ctx.user_id,
        resource_type="table",
        resource_id=board.table_id,
    )
    return granted is not None and GRANT_ORDER[granted] >= GRANT_ORDER[GrantLevel.EDIT]


async def board_allows(db: AsyncSession, ctx: AuthContext, board: TaskBoard, perm: Perm) -> bool:
    return await scope_allows(
        db, ctx, board.scope_kind, board.scope_id, edit=perm is Perm.TABLES_EDIT
    )


async def board_manages(db: AsyncSession, ctx: AuthContext, board: TaskBoard) -> bool:
    """Whether `ctx` may rename, reshape, archive or restore the board itself.

    Narrower than `board_allows`, which is adding and editing its tasks: a whole
    organization works on its board, so changing the board is for a caller whose
    `tables:edit` reaches every table, or for the leader of the board's own scope -
    the group's lead, the project's owner, the person a private board belongs to.
    """
    if not await board_allows(db, ctx, board, Perm.TABLES_EDIT) or ctx.user_id is None:
        return False
    if ctx.scope_for(Perm.TABLES_EDIT) is Scope.ALL or board.scope_kind == "private":
        return True
    if board.scope_kind == "group":
        member = await group_repo.get_member(db, group_id=board.scope_id, user_id=ctx.user_id)
        return member is not None and member.is_lead
    if board.scope_kind == "project":
        project = await project_repo.get(db, board.scope_id, organization_id=ctx.organization_id)
        return project is not None and project.owner_user_id == ctx.user_id
    return False


async def manages_table(db: AsyncSession, ctx: AuthContext, table_id: UUID) -> bool | None:
    """`board_manages` for the board behind `table_id`, or None when it is not a task board."""
    board = await task_repo.for_table(db, table_id, ctx.organization_id)
    return None if board is None else await board_manages(db, ctx, board)


async def table_access(
    db: AsyncSession, ctx: AuthContext, table_id: UUID, perm: Perm
) -> bool | None:
    board = await task_repo.for_table(db, table_id, ctx.organization_id)
    return None if board is None else await board_allows(db, ctx, board, perm)


async def table_audience(db: AsyncSession, ctx: AuthContext) -> tuple[list[UUID], list[UUID]]:
    allowed: list[UUID] = []
    denied: list[UUID] = []
    for board in await task_repo.boards(db, ctx.organization_id):
        (allowed if await board_allows(db, ctx, board, Perm.TABLES_VIEW) else denied).append(
            board.table_id
        )
    return allowed, denied


async def execution_allows(db: AsyncSession, ctx: AuthContext, trigger_id: UUID) -> bool:
    """A task's audience and lifecycle remain authority boundaries after dispatch."""
    from app.repositories import virtual_table_repo
    from app.services.task_columns import from_cells

    link = await task_repo.for_trigger(db, trigger_id)
    if link is None:
        return False
    record = await task_repo.record(db, link.record_id, ctx.organization_id)
    if record is None:
        return False
    board = await task_repo.for_table(db, record.table_id, ctx.organization_id)
    table = await virtual_table_repo.get_table(
        db, record.table_id, organization_id=ctx.organization_id
    )
    return (
        board is not None
        and table is not None
        and table.archived_at is None
        and from_cells(board, record.values).status in {"planned", "in_progress"}
        and await board_allows(db, ctx, board, Perm.TABLES_EDIT)
    )
