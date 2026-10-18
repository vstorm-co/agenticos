"""Shop channel session inbox — Zalo / Messenger live agent (D3 B67)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.channel_bot import ChannelBot
from app.db.models.conversation import Message
from app.repositories import (
    channel_bot_repo,
    channel_identity_repo,
    channel_session_repo,
    conversation_repo,
    knowledge_base_repo,
    shop_ai_settings as shop_ai_settings_repo,
)
from app.repositories import shop_channel_session as shop_session_repo
from app.repositories import shop_widget_conversation as widget_conv_repo
from app.schemas.shop_faq import ShopFaqSuggestionRead
from app.schemas.shop_channel_conversation import (
    ShopChannelMessageList,
    ShopChannelMessageRead,
    ShopChannelSessionList,
    ShopChannelSessionRead,
)
from app.services.shop_catalog_sync import SHOP_CATALOG_KB_NAME
from app.services.channels.base import OutgoingMessage
from app.services.channels import get_adapter
from app.services.shop_channel_handling import (
    HANDLING_MODE_AI,
    HANDLING_MODE_HUMAN,
    STAFF_MESSAGE_MODEL,
)
from app.services.shop_faq_suggestion import ShopFaqSuggestionService
from app.services.shop_zalo_oauth_flow import ensure_shop_zalo_access_token

logger = logging.getLogger(__name__)


def _customer_label(
    identity_display: str | None,
    platform_user_id: str,
    *,
    platform: str = "zalo",
) -> str:
    if identity_display and identity_display.strip() and identity_display != platform_user_id:
        return identity_display.strip()
    prefix = "Messenger" if platform == "messenger" else "Zalo"
    suffix = platform_user_id[-6:] if len(platform_user_id) >= 6 else platform_user_id
    return f"{prefix} #{suffix}"


def _message_sender_type(role: str, model_name: str | None) -> str:
    if role == "user":
        return "customer"
    if role == "assistant" and (model_name or "").strip() == STAFF_MESSAGE_MODEL:
        return "staff"
    return "bot"


class ShopChannelConversationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _build_session_read(
        self,
        session,
        bot,
        identity,
    ) -> ShopChannelSessionRead:
        count = 0
        preview = None
        last_at = session.last_message_at
        if session.conversation_id:
            count = int(
                (
                    await self.db.execute(
                        select(func.count(Message.id)).where(
                            Message.conversation_id == session.conversation_id
                        )
                    )
                ).scalar_one()
            )
            last_msg = (
                await self.db.execute(
                    select(Message)
                    .where(Message.conversation_id == session.conversation_id)
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last_msg is not None:
                preview = (last_msg.content or "")[:160]
                last_at = last_msg.created_at
        return ShopChannelSessionRead(
            id=session.id,
            bot_id=bot.id,
            bot_name=bot.name,
            platform=bot.platform,
            platform_chat_id=session.platform_chat_id,
            conversation_id=session.conversation_id,
            customer_label=_customer_label(
                identity.platform_display_name,
                identity.platform_user_id,
                platform=bot.platform,
            ),
            customer_ref=identity.platform_user_id,
            handling_mode=session.handling_mode or HANDLING_MODE_AI,
            claimed_by_user_id=session.claimed_by_user_id,
            claimed_by_name=session.claimed_by_name,
            claimed_at=session.claimed_at,
            message_count=count,
            preview=preview,
            last_message_at=last_at,
            created_at=session.created_at,
        )

    async def list_sessions(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        platform: str | None = "zalo",
        skip: int = 0,
        limit: int = 50,
    ) -> ShopChannelSessionList:
        from app.services.shop_live_agent_inbox import release_idle_human_sessions

        await release_idle_human_sessions(
            self.db,
            organization_id=organization_id,
            tenant_id=minerp_tenant_id,
        )
        plat = platform.strip().lower() if platform else None
        rows = await shop_session_repo.list_for_shop(
            self.db,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            platform=plat,
            skip=skip,
            limit=limit,
        )
        total = await shop_session_repo.count_for_shop(
            self.db,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            platform=plat,
        )
        items: list[ShopChannelSessionRead] = []
        for session, bot, identity in rows:
            items.append(await self._build_session_read(session, bot, identity))
        return ShopChannelSessionList(items=items, total=total)

    async def _require_session(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        session_id: UUID,
    ):
        session = await shop_session_repo.get_by_id_for_shop(
            self.db,
            session_id,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
        )
        if session is None:
            raise NotFoundError(
                message="Channel session not found",
                details={"session_id": str(session_id)},
            )
        bot = await channel_bot_repo.get_for_org(
            self.db,
            session.bot_id,
            organization_id=organization_id,
        )
        if bot is None:
            raise NotFoundError(
                message="Channel bot not found",
                details={"bot_id": str(session.bot_id)},
            )
        return session, bot

    async def list_messages(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        session_id: UUID,
        skip: int = 0,
        limit: int = 200,
    ) -> ShopChannelMessageList:
        session, _bot = await self._require_session(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            session_id=session_id,
        )
        if session.conversation_id is None:
            return ShopChannelMessageList(items=[], total=0)
        messages = await conversation_repo.get_messages_by_conversation(
            self.db,
            session.conversation_id,
            skip=skip,
            limit=limit,
        )
        total = int(
            (
                await self.db.execute(
                    select(func.count(Message.id)).where(
                        Message.conversation_id == session.conversation_id
                    )
                )
            ).scalar_one()
        )
        items = [
            ShopChannelMessageRead(
                id=m.id,
                role=m.role,
                content=m.content,
                sender_type=_message_sender_type(m.role, m.model_name),
                created_at=m.created_at,
            )
            for m in messages
        ]
        return ShopChannelMessageList(items=items, total=total)

    async def search_messages(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        session_id: UUID,
        query: str,
        limit: int = 100,
    ) -> ShopChannelMessageList:
        session, _bot = await self._require_session(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            session_id=session_id,
        )
        if session.conversation_id is None:
            return ShopChannelMessageList(items=[], total=0)
        messages, total = await widget_conv_repo.search_messages_in_conversations(
            self.db,
            conversation_ids=[session.conversation_id],
            query=query,
            limit=limit,
        )
        items = [
            ShopChannelMessageRead(
                id=m.id,
                role=m.role,
                content=m.content,
                sender_type=_message_sender_type(m.role, m.model_name),
                created_at=m.created_at,
            )
            for m in messages
        ]
        return ShopChannelMessageList(items=items, total=total)

    async def claim_session(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        session_id: UUID,
        claimed_by_user_id: UUID,
        claimed_by_name: str | None = None,
    ) -> ShopChannelSessionRead:
        session, bot = await self._require_session(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            session_id=session_id,
        )
        now = datetime.now(UTC)
        session = await channel_session_repo.update(
            self.db,
            db_session=session,
            update_data={
                "handling_mode": HANDLING_MODE_HUMAN,
                "claimed_by_user_id": claimed_by_user_id,
                "claimed_by_name": (claimed_by_name or "").strip() or None,
                "claimed_at": now,
            },
        )
        identity = await channel_identity_repo.get_by_id(self.db, session.identity_id)
        if identity is None:
            raise NotFoundError(
                message="Channel identity not found",
                details={"identity_id": str(session.identity_id)},
            )
        return await self._build_session_read(session, bot, identity)

    async def release_session(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        session_id: UUID,
    ) -> ShopChannelSessionRead:
        session, bot = await self._require_session(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            session_id=session_id,
        )
        session = await channel_session_repo.update(
            self.db,
            db_session=session,
            update_data={
                "handling_mode": HANDLING_MODE_AI,
                "claimed_by_user_id": None,
                "claimed_by_name": None,
                "claimed_at": None,
            },
        )
        identity = await channel_identity_repo.get_by_id(self.db, session.identity_id)
        if identity is None:
            raise NotFoundError(
                message="Channel identity not found",
                details={"identity_id": str(session.identity_id)},
            )
        return await self._build_session_read(session, bot, identity)

    async def reply_session(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        session_id: UUID,
        text: str,
        staff_user_id: UUID | None = None,
        staff_name: str | None = None,
    ) -> ShopChannelMessageRead:
        session, bot = await self._require_session(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            session_id=session_id,
        )
        if session.conversation_id is None:
            raise BadRequestError(
                message="Session has no conversation thread",
                details={"session_id": str(session_id)},
            )
        if (session.handling_mode or HANDLING_MODE_AI) != HANDLING_MODE_HUMAN:
            raise BadRequestError(
                message="Claim the session before replying to the customer",
                details={"handling_mode": session.handling_mode},
            )
        body = text.strip()
        if not body:
            raise BadRequestError(message="Reply text is required")

        msg = await conversation_repo.create_message(
            self.db,
            conversation_id=session.conversation_id,
            role="assistant",
            content=body,
            model_name=STAFF_MESSAGE_MODEL,
        )
        await channel_session_repo.touch(self.db, session)

        await self._try_send_platform_text(bot=bot, platform_chat_id=session.platform_chat_id, text=body)

        if staff_user_id and session.claimed_by_user_id != staff_user_id:
            await channel_session_repo.update(
                self.db,
                db_session=session,
                update_data={
                    "claimed_by_user_id": staff_user_id,
                    "claimed_by_name": (staff_name or session.claimed_by_name or "").strip()
                    or None,
                    "claimed_at": session.claimed_at or datetime.now(UTC),
                },
            )

        return ShopChannelMessageRead(
            id=msg.id,
            role=msg.role,
            content=msg.content,
            sender_type="staff",
            created_at=msg.created_at,
        )

    async def promote_message_to_faq_suggestion(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        session_id: UUID,
        message_id: UUID,
        kb_id: UUID | None = None,
    ) -> ShopFaqSuggestionRead:
        session, bot = await self._require_session(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            session_id=session_id,
        )
        if session.conversation_id is None:
            raise BadRequestError(
                message="Session has no conversation thread",
                details={"session_id": str(session_id)},
            )

        msg = (
            await self.db.execute(
                select(Message).where(
                    Message.id == message_id,
                    Message.conversation_id == session.conversation_id,
                )
            )
        ).scalar_one_or_none()
        if msg is None:
            raise NotFoundError(
                message="Message not found",
                details={"message_id": str(message_id)},
            )
        if msg.role != "user":
            raise BadRequestError(
                message="Only customer messages can be promoted to FAQ suggestions",
                details={"message_id": str(message_id), "role": msg.role},
            )

        target_kb_id = kb_id or await self._resolve_default_faq_kb_id(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            bot=bot,
        )
        if target_kb_id is None:
            raise BadRequestError(
                message="No FAQ knowledge base configured for suggestions",
                details={"tenant_id": str(minerp_tenant_id)},
            )

        return await ShopFaqSuggestionService(self.db).promote_from_inbox(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            kb_id=target_kb_id,
            question=msg.content or "",
        )

    async def _resolve_default_faq_kb_id(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        bot: ChannelBot,
    ) -> UUID | None:
        if bot.default_kb_id is not None:
            kb = await knowledge_base_repo.get_by_id(self.db, bot.default_kb_id)
            if (
                kb is not None
                and kb.organization_id == organization_id
                and kb.name != SHOP_CATALOG_KB_NAME
            ):
                return kb.id

        settings = await shop_ai_settings_repo.get(self.db, minerp_tenant_id)
        if settings and settings.default_faq_suggestion_kb_id:
            return settings.default_faq_suggestion_kb_id

        for kb in await knowledge_base_repo.list_org_scoped(self.db, organization_id):
            if kb.name != SHOP_CATALOG_KB_NAME:
                return kb.id
        return None

    async def _try_send_platform_text(
        self,
        *,
        bot: ChannelBot,
        platform_chat_id: str,
        text: str,
    ) -> None:
        try:
            adapter = get_adapter(bot.platform)
        except KeyError:
            logger.warning(
                "No channel adapter for platform=%s; staff reply stored only",
                bot.platform,
            )
            return
        try:
            if bot.platform == "zalo":
                token = await ensure_shop_zalo_access_token(self.db, bot)
            else:
                from app.services.channel_bot import unseal_bot_token

                token = unseal_bot_token(bot)
            out = OutgoingMessage(platform_chat_id=platform_chat_id, text=text)
            await adapter.send_message(token, out)
        except Exception:
            logger.exception(
                "Failed to deliver staff reply to platform=%s bot_id=%s",
                bot.platform,
                bot.id,
            )
