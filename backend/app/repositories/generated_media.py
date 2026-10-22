"""Generated media rows: recorded on save, summed for the quota, removed with what owns them."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.generated_media import GeneratedMedia


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID | None,
    filename: str,
    storage_path: str,
    size_bytes: int,
) -> GeneratedMedia:
    """Record one stored file.

    The conversation is linked only where it is this organization's and still
    there: the id comes from the run, and a run with no saved thread - a
    preview, a test run - or one whose thread was deleted mid-run would
    otherwise fail the insert on the foreign key, losing the record of bytes
    that are already stored. Unlinked, the row is still counted and still swept.
    """
    linked = (
        select(Conversation.id)
        .where(Conversation.id == conversation_id, Conversation.organization_id == organization_id)
        .scalar_subquery()
        if conversation_id is not None
        else None
    )
    result = await db.execute(
        insert(GeneratedMedia)
        .values(
            organization_id=organization_id,
            conversation_id=linked,
            filename=filename,
            storage_path=storage_path,
            size_bytes=size_bytes,
        )
        .returning(GeneratedMedia)
    )
    return result.scalar_one()


async def bytes_used(db: AsyncSession, *, organization_id: UUID) -> int:
    """How many bytes of generated media this organization has recorded."""
    total = await db.scalar(
        select(func.coalesce(func.sum(GeneratedMedia.size_bytes), 0)).where(
            GeneratedMedia.organization_id == organization_id
        )
    )
    return int(total or 0)


async def paths_in_conversations(
    db: AsyncSession, *, organization_id: UUID, conversation_ids: Sequence[UUID]
) -> list[str]:
    """The storage paths of what was generated in these threads, in this tenant."""
    if not conversation_ids:
        return []
    rows = await db.execute(
        select(GeneratedMedia.storage_path).where(
            GeneratedMedia.organization_id == organization_id,
            GeneratedMedia.conversation_id.in_(conversation_ids),
        )
    )
    return list(rows.scalars().all())


async def delete_in_conversations(
    db: AsyncSession, *, organization_id: UUID, conversation_ids: Sequence[UUID]
) -> int:
    """Drop the rows of what was generated in these threads; answers how many."""
    if not conversation_ids:
        return 0
    result = cast(
        CursorResult[Any],
        await db.execute(
            delete(GeneratedMedia).where(
                GeneratedMedia.organization_id == organization_id,
                GeneratedMedia.conversation_id.in_(conversation_ids),
            )
        ),
    )
    return result.rowcount or 0


async def delete_by_storage_paths(
    db: AsyncSession, *, organization_id: UUID, storage_paths: Sequence[str]
) -> int:
    """Drop this tenant's rows naming any of these paths; answers how many.

    For a caller that has already unlinked a set of paths of mixed kinds - the
    retention sweep's conversation purge removes attachments and generated
    media together - and must not leave a row counting bytes that are gone.
    """
    if not storage_paths:
        return 0
    result = cast(
        CursorResult[Any],
        await db.execute(
            delete(GeneratedMedia).where(
                GeneratedMedia.organization_id == organization_id,
                GeneratedMedia.storage_path.in_(storage_paths),
            )
        ),
    )
    return result.rowcount or 0


async def expired(db: AsyncSession, *, cutoff: datetime, limit: int) -> list[GeneratedMedia]:
    """The oldest rows created before `cutoff`, across every organization."""
    rows = await db.execute(
        select(GeneratedMedia)
        .where(GeneratedMedia.created_at < cutoff)
        .order_by(GeneratedMedia.created_at)
        .limit(limit)
    )
    return list(rows.scalars().all())


async def delete_by_ids(db: AsyncSession, *, ids: Sequence[UUID]) -> int:
    """Drop these rows; answers how many went."""
    if not ids:
        return 0
    result = cast(
        CursorResult[Any],
        await db.execute(delete(GeneratedMedia).where(GeneratedMedia.id.in_(ids))),
    )
    return result.rowcount or 0
