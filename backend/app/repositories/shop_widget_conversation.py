"""Widget conversation threads scoped by org + Minerp tenant session."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation, Message
from app.repositories import conversation as conversation_repo
from app.services.shop_widget_customer import WIDGET_CONVERSATION_TITLE, widget_conversation_title

WIDGET_CONVERSATION_NS = UUID("a2000001-0001-4000-8000-000000000001")


def widget_conversation_id(*, tenant_id: UUID, session_id: UUID) -> UUID:
    return uuid.uuid5(WIDGET_CONVERSATION_NS, f"{tenant_id}:{session_id}")


async def find_widget_conversation_by_session(
    db: AsyncSession,
    *,
    organization_id: UUID,
    session_id: UUID,
) -> Conversation | None:
    title_prefix = f"{WIDGET_CONVERSATION_TITLE}|{session_id}"
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.organization_id == organization_id,
            Conversation.user_id.is_(None),
            or_(
                Conversation.title == title_prefix,
                Conversation.title.like(f"{title_prefix}|%"),
            ),
        )
        .order_by(func.coalesce(Conversation.updated_at, Conversation.created_at).desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_conversation_ids_for_widget_session(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    session_id: UUID,
) -> list[UUID]:
    ids: set[UUID] = {widget_conversation_id(tenant_id=tenant_id, session_id=session_id)}
    legacy = await find_widget_conversation_by_session(
        db,
        organization_id=organization_id,
        session_id=session_id,
    )
    if legacy is not None:
        ids.add(legacy.id)
    existing: list[UUID] = []
    for cid in ids:
        conv = await conversation_repo.get_conversation_by_id(db, cid)
        if conv is not None and conv.organization_id == organization_id:
            existing.append(cid)
    return existing


def dedupe_widget_session_messages(messages: list[Message]) -> list[Message]:
    seen: set[tuple[str, str, datetime | None]] = set()
    out: list[Message] = []
    ordered = sorted(
        messages,
        key=lambda m: (m.created_at or datetime.min.replace(tzinfo=UTC), str(m.id)),
    )
    for m in ordered:
        ts = m.created_at.replace(microsecond=0) if m.created_at else None
        key = (m.role, (m.content or "").strip(), ts)
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


async def search_messages_in_conversations(
    db: AsyncSession,
    *,
    conversation_ids: list[UUID],
    query: str,
    limit: int = 100,
) -> tuple[list[Message], int]:
    """Case-insensitive content search across one or more widget threads."""
    q = query.strip()
    if not conversation_ids or not q:
        return [], 0
    pattern = f"%{q}%"
    where = (
        Message.conversation_id.in_(conversation_ids),
        Message.content.ilike(pattern),
    )
    total = int(
        (await db.execute(select(func.count(Message.id)).where(*where))).scalar_one() or 0
    )
    if total <= 0:
        return [], 0
    result = await db.execute(
        select(Message)
        .where(*where)
        .order_by(Message.created_at.asc())
        .limit(limit)
    )
    rows = dedupe_widget_session_messages(list(result.scalars().all()))
    return rows, total


async def count_messages_for_widget_session(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    session_id: UUID,
) -> int:
    from sqlalchemy import func, select

    conv_ids = await list_conversation_ids_for_widget_session(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        session_id=session_id,
    )
    if not conv_ids:
        return 0
    result = await db.execute(
        select(func.count(Message.id)).where(Message.conversation_id.in_(conv_ids))
    )
    return int(result.scalar_one() or 0)


async def list_messages_for_widget_session_inbox(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    session_id: UUID,
    skip: int = 0,
    limit: int = 200,
) -> list[Message]:
    conv_ids = await list_conversation_ids_for_widget_session(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        session_id=session_id,
    )
    if not conv_ids:
        return []
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id.in_(conv_ids))
        .order_by(Message.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    return dedupe_widget_session_messages(list(result.scalars().all()))


async def list_messages_for_widget_session_poll(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    session_id: UUID,
    after_message_id: UUID | None = None,
    tail_limit: int = 80,
) -> list[Message]:
    conv_ids = await list_conversation_ids_for_widget_session(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        session_id=session_id,
    )
    if not conv_ids:
        return []

    if after_message_id is not None:
        anchor = await db.get(Message, after_message_id)
        if anchor is not None:
            result = await db.execute(
                select(Message)
                .where(
                    Message.conversation_id.in_(conv_ids),
                    Message.created_at > anchor.created_at,
                )
                .order_by(Message.created_at.asc())
                .limit(tail_limit)
            )
            return dedupe_widget_session_messages(list(result.scalars().all()))

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id.in_(conv_ids))
        .order_by(Message.created_at.desc())
        .limit(tail_limit)
    )
    return dedupe_widget_session_messages(list(reversed(result.scalars().all())))


async def ensure_widget_conversation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    session_id: UUID,
    shopper_user_id: UUID | None = None,
    shopper_display_name: str | None = None,
    shopper_email: str | None = None,
) -> Conversation:
    conv_id = widget_conversation_id(tenant_id=tenant_id, session_id=session_id)
    titled = widget_conversation_title(
        session_id,
        shopper_user_id=shopper_user_id,
        shopper_display_name=shopper_display_name,
        shopper_email=shopper_email,
    )
    conv = await conversation_repo.get_conversation_by_id(db, conv_id)
    if conv is not None:
        if conv.title != titled and (
            conv.title == WIDGET_CONVERSATION_TITLE
            or (conv.title or "").startswith(f"{WIDGET_CONVERSATION_TITLE}|")
        ):
            conv.title = titled
            await db.flush()
        return conv

    conv = Conversation(
        id=conv_id,
        user_id=None,
        organization_id=organization_id,
        title=titled,
    )
    db.add(conv)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await conversation_repo.get_conversation_by_id(db, conv_id)
        if existing is None:
            raise
        return existing
    await db.refresh(conv)
    return conv
