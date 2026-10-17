"""B50 — Shop widget inbox read models for Studio."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.conversation import Conversation, Message
from app.repositories import conversation as conversation_repo
from app.repositories import knowledge_base_repo
from app.repositories import shop_widget_conversation as widget_conv_repo
from app.schemas.shop_faq import ShopFaqSuggestionRead
from app.schemas.shop_widget_conversation import (
    ShopWidgetConversationList,
    ShopWidgetConversationRead,
    ShopWidgetMessageList,
    ShopWidgetMessageRead,
)
from app.services.shop_channel_handling import STAFF_MESSAGE_MODEL
from app.services.shop_widget_customer import (
    WIDGET_CONVERSATION_TITLE,
    is_widget_conversation_title,
    parse_widget_customer_identity,
    resolve_customer_label,
    resolve_customer_ref,
)
from app.services.shop_faq_suggestion import ShopFaqSuggestionService, is_faq_kb
from app.services.shop_live_agent_inbox import release_idle_human_sessions
from app.services.shop_tenant_knowledge import resolve_shop_tenant_kb
from app.services.shop_widget_studio_handling import resolve_widget_handling_row


def widget_message_sender_type(*, role: str, model_name: str | None) -> str:
    if role == "user":
        return "customer"
    if (model_name or "") == STAFF_MESSAGE_MODEL:
        return "staff"
    return "bot"


class ShopWidgetConversationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _build_conversation_read(
        self,
        conv: Conversation,
        *,
        tenant_id: UUID,
    ) -> ShopWidgetConversationRead:
        count = int(
            (
                await self.db.execute(
                    select(func.count(Message.id)).where(Message.conversation_id == conv.id)
                )
            ).scalar_one()
        )
        last_msg = (
            await self.db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        preview = None
        last_at = None
        if last_msg is not None:
            preview = (last_msg.content or "")[:160]
            last_at = last_msg.created_at
        first_user_rows = (
            await self.db.execute(
                select(Message.content)
                .where(
                    Message.conversation_id == conv.id,
                    Message.role == "user",
                )
                .order_by(Message.created_at.asc())
                .limit(3)
            )
        ).scalars().all()
        identity = parse_widget_customer_identity(conv.title)
        handling = await resolve_widget_handling_row(
            self.db,
            organization_id=conv.organization_id,
            tenant_id=tenant_id,
            conversation_id=conv.id,
        )
        return ShopWidgetConversationRead(
            id=conv.id,
            session_id=identity.session_id,
            customer_label=resolve_customer_label(
                identity=identity,
                first_user_messages=list(first_user_rows),
            ),
            customer_ref=resolve_customer_ref(
                identity=identity,
                conversation_id=conv.id,
            ),
            shopper_user_id=identity.shopper_user_id,
            shopper_email=identity.shopper_email,
            message_count=count,
            preview=preview,
            last_message_at=last_at,
            created_at=conv.created_at,
            handling_mode=handling.handling_mode if handling else "ai",
            claimed_by_name=handling.claimed_by_name if handling else None,
        )

    async def get_conversation_read(
        self,
        *,
        organization_id: UUID,
        tenant_id: UUID,
        conversation_id: UUID,
    ) -> ShopWidgetConversationRead:
        conv = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
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
        identity = parse_widget_customer_identity(conv.title)
        if identity.session_id is not None:
            primary_id = widget_conv_repo.widget_conversation_id(
                tenant_id=tenant_id,
                session_id=identity.session_id,
            )
            primary = await conversation_repo.get_conversation_by_id(self.db, primary_id)
            if primary is not None:
                conv = primary
        return await self._build_conversation_read(conv, tenant_id=tenant_id)

    async def list_conversations(
        self,
        *,
        organization_id: UUID,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> ShopWidgetConversationList:
        await release_idle_human_sessions(
            self.db,
            organization_id=organization_id,
            tenant_id=tenant_id,
        )
        base = select(Conversation).where(
            Conversation.organization_id == organization_id,
            Conversation.user_id.is_(None),
            or_(
                Conversation.title == WIDGET_CONVERSATION_TITLE,
                Conversation.title.like(f"{WIDGET_CONVERSATION_TITLE}|%"),
            ),
        )
        rows = (
            await self.db.execute(
                base.order_by(func.coalesce(Conversation.updated_at, Conversation.created_at).desc())
                .offset(skip)
                .limit(limit)
            )
        ).scalars().all()

        items: list[ShopWidgetConversationRead] = []
        for conv in rows:
            identity = parse_widget_customer_identity(conv.title)
            if identity.session_id is not None:
                primary_id = widget_conv_repo.widget_conversation_id(
                    tenant_id=tenant_id,
                    session_id=identity.session_id,
                )
                if conv.id != primary_id:
                    continue
            items.append(await self._build_conversation_read(conv, tenant_id=tenant_id))

        return ShopWidgetConversationList(items=items, total=len(items))

    async def list_messages(
        self,
        *,
        organization_id: UUID,
        tenant_id: UUID,
        conversation_id: UUID,
        skip: int = 0,
        limit: int = 200,
    ) -> ShopWidgetMessageList:
        conv = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
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
        identity = parse_widget_customer_identity(conv.title)
        if identity.session_id is not None:
            total = await widget_conv_repo.count_messages_for_widget_session(
                self.db,
                organization_id=organization_id,
                tenant_id=tenant_id,
                session_id=identity.session_id,
            )
            if skip == 0 and total > limit:
                messages = await widget_conv_repo.list_messages_for_widget_session_poll(
                    self.db,
                    organization_id=organization_id,
                    tenant_id=tenant_id,
                    session_id=identity.session_id,
                    tail_limit=limit,
                )
            else:
                messages = await widget_conv_repo.list_messages_for_widget_session_inbox(
                    self.db,
                    organization_id=organization_id,
                    tenant_id=tenant_id,
                    session_id=identity.session_id,
                    skip=skip,
                    limit=limit,
                )
        else:
            total = int(
                (
                    await self.db.execute(
                        select(func.count(Message.id)).where(
                            Message.conversation_id == conversation_id
                        )
                    )
                ).scalar_one()
            )
            messages = await conversation_repo.get_messages_by_conversation(
                self.db,
                conversation_id,
                skip=skip,
                limit=limit,
            )
        items = [
            ShopWidgetMessageRead(
                id=m.id,
                role=m.role,
                content=m.content,
                sender_type=widget_message_sender_type(
                    role=m.role,
                    model_name=m.model_name,
                ),
                created_at=m.created_at,
            )
            for m in messages
        ]
        return ShopWidgetMessageList(items=items, total=total if identity.session_id else len(items))

    async def search_messages(
        self,
        *,
        organization_id: UUID,
        tenant_id: UUID,
        conversation_id: UUID,
        query: str,
        limit: int = 100,
    ) -> ShopWidgetMessageList:
        conv = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
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
        identity = parse_widget_customer_identity(conv.title)
        if identity.session_id is not None:
            conv_ids = await widget_conv_repo.list_conversation_ids_for_widget_session(
                self.db,
                organization_id=organization_id,
                tenant_id=tenant_id,
                session_id=identity.session_id,
            )
        else:
            conv_ids = [conversation_id]
        messages, total = await widget_conv_repo.search_messages_in_conversations(
            self.db,
            conversation_ids=conv_ids,
            query=query,
            limit=limit,
        )
        items = [
            ShopWidgetMessageRead(
                id=m.id,
                role=m.role,
                content=m.content,
                sender_type=widget_message_sender_type(
                    role=m.role,
                    model_name=m.model_name,
                ),
                created_at=m.created_at,
            )
            for m in messages
        ]
        return ShopWidgetMessageList(items=items, total=total)

    async def promote_message_to_faq_suggestion(
        self,
        *,
        organization_id: UUID,
        tenant_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        kb_id: UUID | None = None,
    ) -> ShopFaqSuggestionRead:
        conv = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
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
        msg = (
            await self.db.execute(
                select(Message).where(
                    Message.id == message_id,
                    Message.conversation_id == conversation_id,
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
            tenant_id=tenant_id,
        )
        if target_kb_id is None:
            raise BadRequestError(
                message="No FAQ knowledge base configured for suggestions",
                details={"tenant_id": str(tenant_id)},
            )
        return await ShopFaqSuggestionService(self.db).promote_from_inbox(
            organization_id=organization_id,
            minerp_tenant_id=tenant_id,
            kb_id=target_kb_id,
            question=msg.content or "",
        )

    async def _resolve_default_faq_kb_id(
        self,
        *,
        organization_id: UUID,
        tenant_id: UUID,
    ) -> UUID | None:
        from app.repositories import shop_ai_settings as shop_ai_settings_repo

        settings_row = await shop_ai_settings_repo.get(self.db, tenant_id)
        if settings_row is not None and settings_row.default_faq_suggestion_kb_id is not None:
            kb = await knowledge_base_repo.get_by_id(
                self.db, settings_row.default_faq_suggestion_kb_id
            )
            if (
                kb is not None
                and kb.organization_id == organization_id
                and is_faq_kb(kb)
            ):
                return kb.id

        ctx = await resolve_shop_tenant_kb(
            self.db,
            tenant_id=tenant_id,
            kb_id=None,
        )
        if ctx is not None and is_faq_kb(ctx.effective_kb):
            return ctx.effective_kb.id
        rows = await knowledge_base_repo.list_org_scoped(self.db, organization_id)
        for kb in rows:
            if is_faq_kb(kb):
                return kb.id
        return None
