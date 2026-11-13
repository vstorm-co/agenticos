"""Coding-agent task change sets (#2480)."""

from datetime import UTC, datetime
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
    revert_patch: str | None = None,
    workspace_ref: dict[str, str] | None = None,
    snapshot_isolated: bool = False,
) -> CodingTaskChange:
    change = CodingTaskChange(
        organization_id=organization_id,
        conversation_id=conversation_id,
        tool_call_id=tool_call_id,
        harness=harness,
        files=files,
        omitted=omitted,
        truncated=truncated,
        revert_patch=revert_patch,
        workspace_ref=workspace_ref,
        snapshot_isolated=snapshot_isolated,
    )
    db.add(change)
    await db.flush()
    await db.refresh(change)
    return change


async def get_in_organization(
    db: AsyncSession, change_id: UUID, *, organization_id: UUID, for_update: bool = False
) -> CodingTaskChange | None:
    query = select(CodingTaskChange).where(
        CodingTaskChange.id == change_id,
        CodingTaskChange.organization_id == organization_id,
    )
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def mark_reverted(db: AsyncSession, *, change: CodingTaskChange) -> CodingTaskChange:
    change.reverted_at = datetime.now(UTC)
    change.revert_job_id = None
    change.revert_failure = None
    await db.flush()
    await db.refresh(change)
    return change


async def has_pending_revert(
    db: AsyncSession, *, organization_id: UUID, conversation_id: UUID, excluding: UUID | None = None
) -> bool:
    query = select(CodingTaskChange.id).where(
        CodingTaskChange.organization_id == organization_id,
        CodingTaskChange.conversation_id == conversation_id,
        CodingTaskChange.revert_job_id.is_not(None),
        CodingTaskChange.reverted_at.is_(None),
    )
    if excluding is not None:
        query = query.where(CodingTaskChange.id != excluding)
    return (await db.scalar(query.limit(1))) is not None


async def save(db: AsyncSession, change: CodingTaskChange) -> None:
    await db.flush()
    await db.refresh(change)
