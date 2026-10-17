"""D3 slice 3 — deterministic Shop widget chat on Agentra (storefront BFF reads)."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import storefront_shop_cskh as shop_client
from app.core.config import settings
from app.schemas.shop_widget import ShopWidgetChatIn, ShopWidgetChatOut, ShopWidgetPollOut
from app.schemas.shop_widget_action import (
    ShopWidgetNavigateAction,
    ShopWidgetOpenCartAction,
)
from app.services import shop_widget_intents as intents
from app.repositories import organization_repo
from app.services.shop_widget_faq_rag import try_widget_faq_rag_reply
from app.services.shop_widget_native_handoff import (
    native_widget_poll_with_db,
    shop_native_widget_handoff_enabled,
    try_widget_handoff_chat_turn,
)

logger = logging.getLogger(__name__)


def shop_native_widget_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_WIDGET_ENABLED


def shop_native_widget_strangler_fallback() -> bool:
    return settings.SHOP_AI_NATIVE_WIDGET_STRANGLER_FALLBACK


def widget_poll_use_strangler() -> bool:
    """Poll needs multi-agent conversation DB until Agentra owns widget threads."""
    if not shop_native_widget_enabled():
        return True
    if settings.SHOP_AI_NATIVE_WIDGET_POLL_NATIVE:
        return False
    return shop_native_widget_strangler_fallback()


def _bff_ready(tenant_id: UUID) -> bool:
    return shop_client.shop_cskh_bff_configured(tenant_id=str(tenant_id))


def _needs_strangler(message: str) -> bool:
    """Paths that require multi-agent (LLM, handoff, cart mutations)."""
    if intents.wants_human_agent(message):
        if shop_native_widget_handoff_enabled():
            return False
        return True
    if intents.is_order_intent(message):
        return True
    return False


async def try_native_widget_chat(
    *,
    tenant_id: UUID,
    data: ShopWidgetChatIn,
    db: AsyncSession | None = None,
) -> ShopWidgetChatOut | None:
    if not shop_native_widget_enabled():
        return None
    if not _bff_ready(tenant_id):
        return None

    message = (data.message or "").strip()
    if not message:
        return None

    if db is not None and shop_native_widget_handoff_enabled():
        org = await organization_repo.get_by_minerp_tenant_id(db, tenant_id)
        if org is not None:
            handoff_out = await try_widget_handoff_chat_turn(
                db,
                organization_id=org.id,
                tenant_id=tenant_id,
                data=data,
            )
            if handoff_out is not None:
                return handoff_out

    if intents.is_faq_only_intent(message):
        if db is not None:
            faq_reply = await try_widget_faq_rag_reply(
                db,
                tenant_id=tenant_id,
                message=message,
                kb_id=data.kb_id,
            )
            if faq_reply:
                return _out(data.session_id, faq_reply)
        if shop_native_widget_strangler_fallback():
            return None

    if _needs_strangler(message) and shop_native_widget_strangler_fallback():
        return None

    greeting = intents.try_greeting_reply(message)
    if greeting:
        return _out(data.session_id, greeting)

    meta = intents.try_meta_chitchat_reply(message)
    if meta:
        return _out(data.session_id, meta)

    order_track = await _try_order_track(tenant_id=tenant_id, message=message)
    if order_track is not None:
        return _out(
            data.session_id,
            order_track.reply,
            actions=order_track.actions,
        )

    if intents.is_cart_view_intent(message):
        return _out(
            data.session_id,
            "Dạ, mình mở giỏ hàng giúp bạn nhé.",
            actions=[ShopWidgetOpenCartAction()],
        )

    recommend = await _try_bestseller(tenant_id=tenant_id, message=message)
    if recommend:
        return _out(data.session_id, recommend)

    browse = await _try_browse(tenant_id=tenant_id, message=message)
    if browse:
        return _out(data.session_id, browse)

    search = await _try_product_search(tenant_id=tenant_id, message=message)
    if search:
        return _out(data.session_id, search)

    if shop_native_widget_strangler_fallback():
        return None

    return _out(
        data.session_id,
        "Mình chưa hiểu rõ câu hỏi. Bạn thử hỏi tên món, **shop bán gì**, hoặc **tra cứu đơn** nhé.",
    )


async def native_widget_poll(
    *,
    session_id: UUID,
    db: AsyncSession | None = None,
    tenant_id: UUID | None = None,
    after_message_id: UUID | None = None,
) -> ShopWidgetPollOut:
    if db is not None and tenant_id is not None and shop_native_widget_handoff_enabled():
        return await native_widget_poll_with_db(
            db,
            tenant_id=tenant_id,
            session_id=session_id,
            after_message_id=after_message_id,
        )
    return ShopWidgetPollOut(session_id=session_id, handling_mode="ai", items=[])


def _out(
    session_id: UUID,
    reply: str,
    *,
    actions: list | None = None,
    handling_mode: str = "ai",
) -> ShopWidgetChatOut:
    return ShopWidgetChatOut(
        reply=reply,
        session_id=session_id,
        actions=actions or [],
        handling_mode=handling_mode,
    )


class _OrderTrackResult:
    __slots__ = ("reply", "actions")

    def __init__(self, reply: str, actions: list | None = None) -> None:
        self.reply = reply
        self.actions = actions or []


async def _try_order_track(*, tenant_id: UUID, message: str) -> _OrderTrackResult | None:
    if not intents.is_order_track_intent(message):
        return None
    tenant_str = str(tenant_id)
    status_token = intents.extract_order_status_token_from_text(message)
    status_href = intents.build_order_status_href(status_token)

    if status_token:
        try:
            order = await shop_client.get_shop_order_by_status_token(
                tenant_id=tenant_str,
                status_token=status_token,
            )
        except Exception:
            return _OrderTrackResult(
                reply=(
                    "Mình chưa tra được với mã tra cứu đó. "
                    "Bạn kiểm tra lại token trên email/SMS, hoặc mở trang tra cứu bên dưới."
                ),
                actions=[ShopWidgetNavigateAction(href=status_href)],
            )
        state = order.get("state_code") or "không rõ"
        return _OrderTrackResult(
            reply=f"Dạ, đơn của bạn hiện ở trạng thái {state}. Mình mở trang chi tiết giúp bạn nhé.",
            actions=[ShopWidgetNavigateAction(href=status_href)],
        )

    order_uuid = intents.extract_product_id_from_text(message)
    if order_uuid:
        try:
            order = await shop_client.get_shop_order(
                tenant_id=tenant_str,
                order_ref=order_uuid,
            )
        except Exception:
            return _OrderTrackResult(
                reply=(
                    "Mình chưa tra được đơn đó. "
                    "Khách thường dùng mã tra cứu (token) trên email/SMS — dán token vào đây nhé."
                ),
                actions=[ShopWidgetNavigateAction(href=intents.build_order_status_href())],
            )
        state = order.get("state_code") or "không rõ"
        return _OrderTrackResult(
            reply=f"Đơn hiện ở trạng thái {state}. Bạn có thể xem chi tiết tại trang theo dõi đơn.",
            actions=[ShopWidgetNavigateAction(href=intents.build_order_status_href())],
        )

    return _OrderTrackResult(
        reply=(
            "Dạ, để tra đơn bạn dùng mã tra cứu shop gửi qua email/SMS sau khi đặt hàng — "
            "dán mã vào đây hoặc mở trang tra cứu bên dưới."
        ),
        actions=[ShopWidgetNavigateAction(href=intents.build_order_status_href())],
    )


async def _try_bestseller(*, tenant_id: UUID, message: str) -> str | None:
    if not intents.is_catalog_recommend_intent(message):
        return None
    tenant_str = str(tenant_id)
    try:
        payload = await shop_client.get_shop_bestsellers(tenant_id=tenant_str, limit=8, days=30)
    except Exception:
        logger.warning("widget_bestseller_failed", extra={"tenant_id": tenant_str}, exc_info=True)
        return (
            "Dạ, mình chưa lấy được dữ liệu bán chạy lúc này. "
            "Bạn thử hỏi tên món cụ thể nhé!"
        )
    items = payload.get("items") or []
    days = int(payload.get("days") or 30)
    if items:
        return intents.format_bestseller_reply(items, days=days)
    try:
        catalog = await shop_client.list_shop_catalog_items(tenant_id=tenant_str, limit=8)
    except Exception:
        return (
            "Dạ, mình chưa lấy được dữ liệu bán chạy lúc này. "
            "Bạn thử hỏi tên món cụ thể nhé!"
        )
    browse = intents.format_catalog_browse_reply(catalog.get("items") or [])
    return (
        f"Dạ, {days} ngày qua chưa có đủ đơn để thống kê — menu shop hiện có:\n"
        + "\n".join(browse.splitlines()[1:])
    )


async def _try_browse(*, tenant_id: UUID, message: str) -> str | None:
    if not intents.is_catalog_browse_intent(message):
        return None
    tenant_str = str(tenant_id)
    try:
        payload = await shop_client.list_shop_catalog_items(tenant_id=tenant_str, limit=8)
    except Exception:
        return (
            "Dạ, mình chưa lấy được danh sách món lúc này. "
            "Bạn thử hỏi tên món cụ thể nhé!"
        )
    return intents.format_catalog_browse_reply(payload.get("items") or [])


async def _try_product_search(*, tenant_id: UUID, message: str) -> str | None:
    if not intents.is_product_search_intent(message):
        return None
    tenant_str = str(tenant_id)
    item_id = intents.extract_product_id_from_text(message)
    if item_id:
        try:
            item = await shop_client.get_shop_product(tenant_id=tenant_str, product_ref=item_id)
            return intents.format_product_search_vi({"items": [item], "total": 1})
        except Exception:
            pass
    try:
        payload = await shop_client.search_shop_products(
            tenant_id=tenant_str,
            query=message,
            limit=5,
        )
    except Exception:
        return None
    return intents.format_product_search_vi(payload)
