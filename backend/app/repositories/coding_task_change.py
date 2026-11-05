"""Coding-agent task change sets (#2480)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.coding_task_change import CodingTaskChange


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    tool_call_id: str | None,
    harness: str,
    files: list[dict[str, object]],
    omitted: int,
    truncated: bool,
) -> CodingTaskChange:
    change = CodingTaskChange(
        organization_id=organization_id,
        conversation_id=conversation_id,
        tool_call_id=tool_call_id,
        harness=harness,
        files=files,
        omitted=omitted,
        truncated=truncated,
    )
    db.add(change)
    await db.flush()
    await db.refresh(change)
    return change


async def get_in_organization(
    db: AsyncSession, change_id: UUID, *, organization_id: UUID
) -> CodingTaskChange | None:
    result = await db.execute(
        select(CodingTaskChange).where(
            CodingTaskChange.id == change_id,
            CodingTaskChange.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()
