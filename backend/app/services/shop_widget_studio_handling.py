"""B50 — Studio claim / release / reply on Agentra widget threads."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.conversation import Conversation, Message
from app.repositories import conversation as conversation_repo
from app.repositories import shop_widget_conversation as widget_conv_repo
from app.repositories import shop_widget_handling as handling_repo
from app.services.shop_channel_handling import HANDLING_MODE_AI, HANDLING_MODE_HUMAN, STAFF_MESSAGE_MODEL
from app.services.shop_widget_customer import is_widget_conversation_title


async def _require_widget_conv(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
) -> Conversation:
    conv = await conversation_repo.get_conversation_by_id(db, conversation_id)
    if (
        conv is None
        or conv.organization_id != organization_id
        or conv.user_id is not None
        or not is_widget_conversation_title(conv.title)
    ):
        raise NotFoundError(
            message="Widget conversation not found",
            details={"conversation_id": str(conversation_id)},
        )
    return conv


async def _handling_conversation_ids(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
) -> list[UUID]:
    conv = await conversation_repo.get_conversation_by_id(db, conversation_id)
    if conv is None or conv.organization_id != organization_id:
        return [conversation_id]
    from app.services.shop_widget_customer import parse_widget_session_id

    session_id = parse_widget_session_id(conv.title)
    if session_id is None:
        return [conversation_id]
    return await widget_conv_repo.list_conversation_ids_for_widget_session(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        session_id=session_id,
    )


async def apply_handling_update(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    update_data: dict,
) -> None:
    for cid in await _handling_conversation_ids(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    ):
        row = await handling_repo.get_or_create_ai(db, conversation_id=cid)
        await handling_repo.update(db, row=row, update_data=update_data)


async def resolve_widget_handling_row(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
):
    from app.db.models.shop_widget_handling import ShopWidgetHandling

    best: ShopWidgetHandling | None = None
    best_pri = 0
    priority = {"human": 3, "queued": 2, "ai": 1}
    for cid in await _handling_conversation_ids(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    ):
        row = await handling_repo.get_by_conversation_id(db, cid)
        if row is None:
            continue
        pri = priority.get(row.handling_mode or "ai", 0)
        if pri > best_pri:
            best = row
            best_pri = pri
    return best


async def claim_widget_conversation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    claimed_by_user_id: UUID,
    claimed_by_name: str | None,
) -> None:
    await _require_widget_conv(db, organization_id=organization_id, conversation_id=conversation_id)
    await apply_handling_update(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        update_data={
            "handling_mode": HANDLING_MODE_HUMAN,
            "claimed_by_user_id": claimed_by_user_id,
            "claimed_by_name": (claimed_by_name or "").strip() or None,
            "claimed_at": datetime.now(UTC),
        },
    )


async def release_widget_conversation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
) -> None:
    await _require_widget_conv(db, organization_id=organization_id, conversation_id=conversation_id)
    await apply_handling_update(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        update_data={
            "handling_mode": HANDLING_MODE_AI,
            "claimed_by_user_id": None,
            "claimed_by_name": None,
            "claimed_at": None,
        },
    )


async def reply_widget_conversation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    text: str,
) -> Message:
    conv = await _require_widget_conv(db, organization_id=organization_id, conversation_id=conversation_id)
    row = await resolve_widget_handling_row(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        conversation_id=conv.id,
    )
    if row is None or (row.handling_mode or HANDLING_MODE_AI) != HANDLING_MODE_HUMAN:
        raise BadRequestError(
            message="Claim the conversation before replying",
            details={"handling_mode": row.handling_mode if row else HANDLING_MODE_AI},
        )
    body = text.strip()
    if not body:
        raise BadRequestError(message="Reply text is required")
    return await conversation_repo.create_message(
        db,
        conversation_id=conversation_id,
        role="assistant",
        content=body,
        model_name=STAFF_MESSAGE_MODEL,
    )
