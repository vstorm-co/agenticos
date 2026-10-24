"""Generated media rows: recorded on save, summed for the quota, removed with what owns them.

Beside them, the quota a generation call in flight holds until its file is
recorded (`GeneratedMediaReservation`).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, CursorResult, and_, delete, func, insert, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.generated_media import GeneratedMedia, GeneratedMediaReservation


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
    that are already stored. Unlinked, the row is still counted and is swept
    after the short lifetime of a file with no conversation (`expired`).
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
    """How many bytes of generated media this organization keeps.

    Every row counts, a row with no conversation too - a preview's, a test
    run's, a channel `/btw` aside's, an API run's that named no thread. No
    member can delete anything to free those, so the sweep removes them after a
    short lifetime of their own (`expired`), even with retention off, which is
    what keeps a burst of them from refusing the organization for long.
    """
    total = await db.scalar(
        select(func.coalesce(func.sum(GeneratedMedia.size_bytes), 0)).where(
            GeneratedMedia.organization_id == organization_id
        )
    )
    return int(total or 0)


async def bytes_reserved(db: AsyncSession, *, organization_id: UUID, since: datetime) -> int:
    """How many bytes this organization's calls in flight hold, made since `since`.

    A claim older than that belonged to a call that died with its process
    before it could release it; it is not counted, and the sweep removes it.
    """
    total = await db.scalar(
        select(func.coalesce(func.sum(GeneratedMediaReservation.size_bytes), 0)).where(
            GeneratedMediaReservation.organization_id == organization_id,
            GeneratedMediaReservation.created_at >= since,
        )
    )
    return int(total or 0)


async def reserve(db: AsyncSession, *, organization_id: UUID, size_bytes: int) -> UUID:
    """Hold `size_bytes` of this organization's quota for one call; answers the claim's id.

    The caller holds the organization's generated-media lock, taken before it
    read what is used, so the check and this write are one step to every other
    admission.
    """
    result = await db.execute(
        insert(GeneratedMediaReservation)
        .values(organization_id=organization_id, size_bytes=size_bytes)
        .returning(GeneratedMediaReservation.id)
    )
    return result.scalar_one()


async def release(db: AsyncSession, *, organization_id: UUID, reservation_id: UUID) -> None:
    """Drop one claim of this organization's; a claim already gone is no error."""
    await db.execute(
        delete(GeneratedMediaReservation).where(
            GeneratedMediaReservation.id == reservation_id,
            GeneratedMediaReservation.organization_id == organization_id,
        )
    )


async def delete_stale_reservations(db: AsyncSession, *, before: datetime) -> int:
    """Drop every claim made before `before`, across organizations; answers how many."""
    result = cast(
        CursorResult[Any],
        await db.execute(
            delete(GeneratedMediaReservation).where(GeneratedMediaReservation.created_at < before)
        ),
    )
    return result.rowcount or 0


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


async def delete_in_conversations_of_user(db: AsyncSession, *, user_id: UUID) -> list[str]:
    """Drop the rows of what was generated in this person's conversations; answer their paths.

    Every organization's: an account deletion takes the person's conversations
    in all of them.
    """
    owned = select(Conversation.id).where(Conversation.user_id == user_id)
    rows = await db.execute(
        delete(GeneratedMedia)
        .where(GeneratedMedia.conversation_id.in_(owned))
        .returning(GeneratedMedia.storage_path)
    )
    return list(rows.scalars().all())


async def expired(
    db: AsyncSession,
    *,
    cutoff: datetime | None,
    unlinked_cutoff: datetime,
    limit: int,
    after: tuple[datetime, UUID] | None = None,
) -> list[GeneratedMedia]:
    """The oldest expired rows, across every organization.

    A row is expired when it has no conversation and was created before
    `unlinked_cutoff`, or was created before `cutoff` - `None` with retention
    off, when only the first holds.

    `after` is the `(created_at, id)` of the last row a previous batch read:
    rows the sweep could not delete stay in the table, and reading past them
    rather than from the start is what keeps them from being every batch's
    first rows.
    """
    bounds: list[ColumnElement[bool]] = [
        and_(GeneratedMedia.conversation_id.is_(None), GeneratedMedia.created_at < unlinked_cutoff)
    ]
    if cutoff is not None:
        bounds.append(GeneratedMedia.created_at < cutoff)
    query = select(GeneratedMedia).where(or_(*bounds))
    if after is not None:
        query = query.where(tuple_(GeneratedMedia.created_at, GeneratedMedia.id) > tuple_(*after))
    rows = await db.execute(
        query.order_by(GeneratedMedia.created_at, GeneratedMedia.id).limit(limit)
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
