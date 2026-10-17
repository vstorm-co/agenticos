"""D3 slice 6 — deterministic merchant assistant chat via storefront BFF."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.clients import storefront_shop_cskh as shop_client
from app.core.config import settings
from app.services import shop_widget_intents as intents


def shop_native_merchant_chat_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_MERCHANT_CHAT_ENABLED


def shop_native_merchant_chat_strangler_fallback() -> bool:
    return settings.SHOP_AI_NATIVE_MERCHANT_CHAT_STRANGLER_FALLBACK


def _bff_ready(tenant_id: UUID) -> bool:
    return shop_client.shop_cskh_bff_configured(tenant_id=str(tenant_id))


def _format_merchant_order_reply(order: dict) -> str:
    state = order.get("state_code") or "không rõ"
    order_id = order.get("id") or order.get("order_id")
    total = order.get("total_amount") or order.get("grand_total")
    lines = ["Thông tin đơn hàng:", f"- Trạng thái: {state}"]
    if total is not None:
        lines.append(f"- Tổng tiền: {float(total):,.0f}đ")
    if order_id:
        lines.append(f"- Mã đơn: {order_id}")
    return "\n".join(lines)


async def _try_merchant_order_reply(*, tenant_id: str, message: str) -> str | None:
    if not intents.is_order_track_intent(message):
        return None
    status_token = intents.extract_order_status_token_from_text(message)
    order_uuid = intents.extract_product_id_from_text(message)
    if status_token:
        try:
            order = await shop_client.get_shop_order_by_status_token(
                tenant_id=tenant_id,
                status_token=status_token,
            )
        except Exception:
            return (
                "Không tra được với mã tra cứu đó.\n"
                "Kiểm tra lại token trên email/SMS khách nhận sau checkout."
            )
        return _format_merchant_order_reply(order)
    if order_uuid:
        try:
            order = await shop_client.get_shop_order(
                tenant_id=tenant_id,
                order_ref=order_uuid,
            )
        except Exception:
            return (
                "Không tìm thấy đơn với UUID đó.\n"
                "Thử mã tra cứu (token) ngắn hơn mà khách nhận sau checkout."
            )
        return _format_merchant_order_reply(order)
    return (
        "Để tra đơn, gửi một trong các thông tin sau:\n"
        "- Mã tra cứu (token khách nhận sau checkout)\n"
        "- UUID đơn hàng\n\n"
        "Mình sẽ tra trạng thái ngay khi có mã."
    )


async def _try_merchant_bestseller_reply(*, tenant_id: str, message: str) -> str | None:
    if not intents.is_catalog_recommend_intent(message):
        return None
    try:
        payload = await shop_client.get_shop_bestsellers(tenant_id=tenant_id, limit=8, days=30)
    except Exception:
        payload = None
    items = (payload or {}).get("items") or []
    days = int((payload or {}).get("days") or 30)
    if not items:
        return (
            f"{days} ngày qua chưa có đơn WEB đủ để thống kê bán chạy.\n"
            "Bạn có thể xem catalog trong Studio hoặc hỏi tên sản phẩm cụ thể."
        )
    body = intents.format_bestseller_reply(items, days=days, max_items=8)
    lines = body.splitlines()
    if lines:
        lines[0] = f"Top bán chạy ({days} ngày qua):"
        lines.append("Hỏi tên món hoặc mở Studio → Sản phẩm để xem chi tiết.")
    return "\n".join(lines)


async def try_native_merchant_chat(
    *,
    tenant_id: UUID,
    message: str,
) -> str | None:
    if not shop_native_merchant_chat_enabled():
        return None
    if not _bff_ready(tenant_id):
        return None
    tenant_str = str(tenant_id)
    text = (message or "").strip()
    if not text:
        return None

    order_reply = await _try_merchant_order_reply(tenant_id=tenant_str, message=text)
    if order_reply is not None:
        return order_reply

    bestseller = await _try_merchant_bestseller_reply(tenant_id=tenant_str, message=text)
    if bestseller is not None:
        return bestseller

    if shop_native_merchant_chat_strangler_fallback():
        return None

    return (
        "Mình chưa chắc bạn cần gì. Thử hỏi **top bán chạy**, **tra đơn** (kèm token/UUID), "
        "hoặc mô tả sản phẩm/đơn cụ thể."
    )


def format_merchant_chat_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
