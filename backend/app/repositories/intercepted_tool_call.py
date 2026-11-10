"""Rows in `intercepted_tool_calls` - what an isolated run did not execute."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.intercepted_tool_call import InterceptedToolCall


async def add_many(
    db: AsyncSession,
    *,
    run_id: UUID,
    organization_id: UUID,
    calls: Sequence[InterceptedToolCall],
) -> None:
    """Append a run's intercepted calls after the ones already written.

    Numbered on from what the run holds, because a run can be finished twice -
    parked and resumed - and the second batch continues the first.
    """
    if not calls:
        return
    result = await db.execute(
        select(func.coalesce(func.max(InterceptedToolCall.sequence), -1)).where(
            InterceptedToolCall.run_id == run_id,
            InterceptedToolCall.organization_id == organization_id,
        )
    )
    start = int(result.scalar_one()) + 1
    for offset, call in enumerate(calls):
        call.run_id = run_id
        call.organization_id = organization_id
        call.sequence = start + offset
        db.add(call)
    await db.flush()


async def list_for_run(
    db: AsyncSession, *, run_id: UUID, organization_id: UUID
) -> list[InterceptedToolCall]:
    """One run's intercepted calls, in the order they were made."""
    result = await db.execute(
        select(InterceptedToolCall)
        .where(
            InterceptedToolCall.run_id == run_id,
            InterceptedToolCall.organization_id == organization_id,
        )
        .order_by(InterceptedToolCall.sequence)
    )
    return list(result.scalars().all())
