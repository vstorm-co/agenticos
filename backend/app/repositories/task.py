"""Task bindings. Record contents and revisions remain owned by Virtual Tables."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_trigger import AgentTrigger
from app.db.models.outcome import Outcome
from app.db.models.suggestion import Suggestion
from app.db.models.task_board import TaskBoard, TaskLink
from app.db.models.virtual_table import VirtualTable, VirtualTableRecord


async def boards(db: AsyncSession, organization_id: UUID) -> list[TaskBoard]:
    return list(
        (
            await db.scalars(select(TaskBoard).where(TaskBoard.organization_id == organization_id))
        ).all()
    )


async def for_scope(
    db: AsyncSession, organization_id: UUID, kind: str, scope_id: UUID
) -> TaskBoard | None:
    return await db.scalar(
        select(TaskBoard).where(
            TaskBoard.organization_id == organization_id,
            TaskBoard.scope_kind == kind,
            TaskBoard.scope_id == scope_id,
        )
    )


async def for_table(db: AsyncSession, table_id: UUID, organization_id: UUID) -> TaskBoard | None:
    found = await db.execute(
        select(TaskBoard).where(
            TaskBoard.table_id == table_id, TaskBoard.organization_id == organization_id
        )
    )
    return found.scalar_one_or_none()


async def add_board(db: AsyncSession, board: TaskBoard) -> TaskBoard:
    db.add(board)
    await db.flush()
    return board


async def link(db: AsyncSession, record_id: UUID) -> TaskLink | None:
    return await db.get(TaskLink, record_id)


async def add_link(db: AsyncSession, value: TaskLink) -> TaskLink:
    db.add(value)
    await db.flush()
    return value


async def for_outcome(db: AsyncSession, outcome_id: UUID) -> TaskLink | None:
    return await db.scalar(select(TaskLink).where(TaskLink.outcome_id == outcome_id))


async def for_trigger(db: AsyncSession, trigger_id: UUID) -> TaskLink | None:
    return await db.scalar(select(TaskLink).where(TaskLink.trigger_id == trigger_id))


async def record(
    db: AsyncSession, record_id: UUID, organization_id: UUID, *, lock: bool = False
) -> VirtualTableRecord | None:
    query = (
        select(VirtualTableRecord)
        .join(TaskBoard, TaskBoard.table_id == VirtualTableRecord.table_id)
        .where(VirtualTableRecord.id == record_id, TaskBoard.organization_id == organization_id)
    )
    if lock:
        query = query.with_for_update(of=VirtualTableRecord).execution_options(
            populate_existing=True
        )
    return await db.scalar(query)


async def flush(db: AsyncSession) -> None:
    await db.flush()


async def case(db: AsyncSession, outcome_id: UUID, organization_id: UUID) -> Outcome | None:
    return await db.scalar(
        select(Outcome)
        .where(Outcome.id == outcome_id, Outcome.organization_id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def lock_case_task(db: AsyncSession, outcome_id: UUID, organization_id: UUID) -> None:
    """Match table writers' lock order before locking the associated Inbox case."""
    from app.repositories import virtual_table_repo

    binding = await for_outcome(db, outcome_id)
    if binding is None:
        return
    board = await db.get(TaskBoard, binding.board_id)
    if board is not None and board.organization_id == organization_id:
        await virtual_table_repo.get_table(
            db, board.table_id, organization_id=organization_id, for_share=True
        )
        await record(db, binding.record_id, organization_id, lock=True)


async def finding_for_case(
    db: AsyncSession, outcome_id: UUID, organization_id: UUID, user_id: UUID
) -> Suggestion | None:
    return await db.scalar(
        select(Suggestion).where(
            Suggestion.outcome_id == outcome_id,
            Suggestion.organization_id == organization_id,
            Suggestion.user_id == user_id,
        )
    )


async def in_scope(
    db: AsyncSession, kind: str, scope_id: UUID, organization_id: UUID | None
) -> list[TaskBoard]:
    query = select(TaskBoard).where(TaskBoard.scope_kind == kind, TaskBoard.scope_id == scope_id)
    if organization_id is not None:
        query = query.where(TaskBoard.organization_id == organization_id)
    return list(await db.scalars(query.order_by(TaskBoard.organization_id)))


async def board_links(db: AsyncSession, board: TaskBoard) -> list[TaskLink]:
    return list(await db.scalars(select(TaskLink).where(TaskLink.board_id == board.id)))


async def purge_table(db: AsyncSession, board: TaskBoard) -> None:
    await db.execute(
        delete(VirtualTable).where(
            VirtualTable.id == board.table_id, VirtualTable.organization_id == board.organization_id
        )
    )
    await db.flush()


async def has_agent_execution(db: AsyncSession, organization_id: UUID, agent_id: UUID) -> bool:
    result = await db.execute(
        select(TaskLink.record_id)
        .join(AgentTrigger, TaskLink.trigger_id == AgentTrigger.id)
        .where(
            AgentTrigger.organization_id == organization_id,
            AgentTrigger.agent_id == agent_id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def parked_runs(db: AsyncSession, organization_id: UUID, trigger_id: UUID) -> list[UUID]:
    from app.db.models.agent_run import AgentRun, RunStatus

    return list(
        (
            await db.scalars(
                select(AgentRun.id).where(
                    AgentRun.organization_id == organization_id,
                    AgentRun.trigger_id == trigger_id,
                    AgentRun.status.in_(
                        [RunStatus.AWAITING_APPROVAL.value, RunStatus.AWAITING_ANSWER.value]
                    ),
                )
            )
        ).all()
    )
