"""Durable resumed answers, deduplicated by their source run."""

from uuid import UUID

from sqlalchemy import literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import TriggerDeliveryStatus
from app.db.models.routine_delivery import RoutineDelivery


async def create(
    db: AsyncSession, *, run_id: UUID, organization_id: UUID, trigger_id: UUID, answer: str
) -> bool:
    """Whether this transaction admitted the first handoff for the run."""
    admitted = await db.scalar(
        insert(RoutineDelivery)
        .from_select(
            ["run_id", "organization_id", "owner_user_id", "trigger_id", "answer", "status"],
            select(
                AgentRun.id,
                AgentRun.organization_id,
                AgentRun.user_id,
                AgentRun.routine_origin_id,
                literal(answer),
                literal("pending"),
            ).where(
                AgentRun.id == run_id,
                AgentRun.organization_id == organization_id,
                AgentRun.routine_origin_id == trigger_id,
                AgentRun.routine_kind == "trigger",
                AgentRun.parent_run_id.is_(None),
                AgentRun.user_id.is_not(None),
                AgentRun.status == RunStatus.COMPLETED.value,
            ),
        )
        .on_conflict_do_nothing(index_elements=[RoutineDelivery.run_id])
        .returning(RoutineDelivery.run_id)
    )
    return admitted is not None


async def get(
    db: AsyncSession, *, run_id: UUID, organization_id: UUID, for_update: bool = False
) -> RoutineDelivery | None:
    statement = select(RoutineDelivery).where(
        RoutineDelivery.run_id == run_id, RoutineDelivery.organization_id == organization_id
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(statement)


async def settle(
    db: AsyncSession,
    *,
    delivery: RoutineDelivery,
    status: TriggerDeliveryStatus,
    conversation_id: UUID | None = None,
) -> None:
    delivery.status = status.value
    delivery.conversation_id = conversation_id
    await db.flush()
