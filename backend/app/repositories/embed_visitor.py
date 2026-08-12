"""EmbedVisitor repository - the thread a returning visitor comes back to."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.embed_visitor import EmbedVisitor


async def get(db: AsyncSession, *, embed_id: UUID, visitor_key: str) -> EmbedVisitor | None:
    """One visitor's row, scoped to the embed that minted their key.

    Scoped on both columns rather than on the key alone: a key is unguessable but
    it is still a value from a browser, and the tenant this resolves inside is
    read off the embed the caller was already admitted to.
    """
    result = await db.execute(
        select(EmbedVisitor).where(
            EmbedVisitor.embed_id == embed_id, EmbedVisitor.visitor_key == visitor_key
        )
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession, *, embed_id: UUID, visitor_key: str, conversation_id: UUID | None
) -> EmbedVisitor:
    visitor = EmbedVisitor(
        embed_id=embed_id,
        visitor_key=visitor_key,
        conversation_id=conversation_id,
        last_seen_at=datetime.now(UTC),
    )
    db.add(visitor)
    await db.flush()
    await db.refresh(visitor)
    return visitor


async def touch(
    db: AsyncSession, *, db_visitor: EmbedVisitor, conversation_id: UUID | None = None
) -> EmbedVisitor:
    """Record that the key was used, and which thread it now names."""
    db_visitor.last_seen_at = datetime.now(UTC)
    if conversation_id is not None:
        db_visitor.conversation_id = conversation_id
    await db.flush()
    await db.refresh(db_visitor)
    return db_visitor
