"""Visual repository - the index of drawings, never the drawings themselves."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.visual import Visual


async def record(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    tool_call_id: str,
    agent_id: UUID | None,
    user_id: UUID | None,
    title: str,
    kind: str,
    revision_of: str | None,
) -> None:
    """Index one drawing. A call already indexed - a retried turn - is left as it is."""
    await db.execute(
        pg_insert(Visual)
        .values(
            organization_id=organization_id,
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            agent_id=agent_id,
            user_id=user_id,
            title=title[:200],
            kind=kind,
            revision_of=revision_of,
        )
        .on_conflict_do_nothing(index_elements=["conversation_id", "tool_call_id"])
    )
    await db.flush()


async def recent(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, limit: int
) -> list[Visual]:
    """A person's latest drawings in one organization, newest first."""
    result = await db.execute(
        select(Visual)
        .where(Visual.organization_id == organization_id, Visual.user_id == user_id)
        .order_by(Visual.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get(db: AsyncSession, visual_id: UUID, *, organization_id: UUID) -> Visual | None:
    result = await db.execute(
        select(Visual).where(Visual.id == visual_id, Visual.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def get_by_call(
    db: AsyncSession, *, conversation_id: UUID, tool_call_id: str
) -> Visual | None:
    result = await db.execute(
        select(Visual).where(
            Visual.conversation_id == conversation_id, Visual.tool_call_id == tool_call_id
        )
    )
    return result.scalar_one_or_none()


async def update(
    db: AsyncSession,
    *,
    db_visual: Visual,
    artifact_id: UUID | None = None,
    thumbnail_path: str | None = None,
) -> Visual:
    """Record the app a drawing was saved as, or where its thumbnail is kept."""
    if artifact_id is not None:
        db_visual.artifact_id = artifact_id
    if thumbnail_path is not None:
        db_visual.thumbnail_path = thumbnail_path
    await db.flush()
    await db.refresh(db_visual)
    return db_visual
