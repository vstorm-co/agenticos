"""EmbedVisitor repository - the thread a returning visitor comes back to."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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


async def claim(db: AsyncSession, *, embed_id: UUID, visitor_key: str) -> EmbedVisitor:
    """This visitor's row, created if this is their first sight of the page.

    One statement rather than a read and then a write, because two tabs on one
    link share a `localStorage` key: read-then-write has both of them miss, both
    insert, and the second commit violate `uq_embed_visitor_key` - which the
    socket's handler turns into "Something went wrong" for whichever tab lost.
    Opening a bookmarked link twice is not a race worth losing a conversation to.

    `ON CONFLICT` updates `last_seen_at` rather than doing nothing, so the row
    comes back either way and this is also the touch: a returning visitor's
    timestamp is what a retention policy will have to read.
    """
    now = datetime.now(UTC)
    statement = (
        pg_insert(EmbedVisitor)
        .values(embed_id=embed_id, visitor_key=visitor_key, last_seen_at=now)
        .on_conflict_do_update(constraint="uq_embed_visitor_key", set_={"last_seen_at": now})
        .returning(EmbedVisitor)
    )
    result = await db.execute(statement)
    return result.scalars().one()


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
