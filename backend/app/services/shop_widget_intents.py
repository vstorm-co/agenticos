"""Deterministic Shop widget intents (ported subset from multi-agent shop_product_prefetch)."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_STATUS_TOKEN_QUERY_RE = re.compile(
    r"(?:[?&]token=|token\s*[:=]\s*)([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_OPAQUE_STATUS_TOKEN_RE = re.compile(r"([A-Za-z0-9_-]{12,})")

_ORDER_TRACK_MARKERS = (
    "kiểm tra đơn",
    "kiem tra don",
    "xem đơn hàng",
    "xem don hang",
    "tra cứu đơn",
    "tra cuu don",
    "theo dõi đơn",
    "theo doi don",
    "tra đơn",
    "tra don",
    "trạng thái đơn",
    "trang thai don",
    "đơn hàng của tôi",
    "don hang cua toi",
    "order status",
    "track order",
)

_CATALOG_BROWSE_MARKERS = (
    "ban gi",
    "bán gì",
    "shop ban gi",
    "shop bán gì",
    "co gi",
    "có gì",
    "menu",
    "thuc don",
    "thực đơn",
    "mon gi",
    "món gì",
    "xem menu",
)

_CATALOG_RECOMMEND_MARKERS = (
    "ban chay",
    "bán chạy",
    "mon nao",
    "món nào",
    "best seller",
    "goi y",
    "gợi ý",
)

_FAQ_ONLY_MARKERS = (
    "giao hàng",
    "giao hang",
    "ship",
    "đổi trả",
    "doi tra",
    "bảo hành",
    "bao hanh",
    "thanh toán",
    "thanh toan",
    "cod",
    "chính sách",
    "chinh sach",
)

_CART_VIEW_MARKERS = (
    "xem giỏ",
    "xem gio",
    "mở giỏ",
    "mo gio",
    "giỏ hàng",
    "gio hang",
    "open cart",
    "view cart",
)

_ORDER_MARKERS = (
    "đặt",
    "dat",
    "mua",
    "order",
    "thêm vào giỏ",
    "them vao gio",
    "add to cart",
)

_GREETING_OR_CHITCHAT = (
    "xin chao",
    "xin chào",
    "cam on",
    "cảm ơn",
    "hello",
    "hi ",
    "help",
    "chao ban",
    "chào bạn",
)

_META_CHITCHAT_MARKERS = (
    "bot",
    "chatbot",
    "tro ly ai",
    "trợ lý ai",
    "nguoi that",
    "người thật",
    "ban la gi",
    "bạn là gì",
    "la bot",
    "là bot",
)

_ESCALATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"gap\s+nhan\s+vien"),
    re.compile(r"nhan\s+vien"),
    re.compile(r"live\s+agent"),
    re.compile(r"human\s+agent"),
    re.compile(r"chuyen\s+cskh"),
)


def _ascii_fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _normalize_escalation(text: str) -> str:
    lowered = text.casefold().strip()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def wants_human_agent(message: str) -> bool:
    normalized = _normalize_escalation(message)
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _ESCALATION_PATTERNS)


def extract_product_id_from_text(text: str) -> str | None:
    match = _UUID_RE.search(text or "")
    return match.group(0) if match else None


def extract_order_status_token_from_text(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    query_match = _STATUS_TOKEN_QUERY_RE.search(raw)
    if query_match:
        return query_match.group(1)
    uuid_match = _UUID_RE.search(raw)
    best: str | None = None
    for match in _OPAQUE_STATUS_TOKEN_RE.finditer(raw):
        candidate = match.group(1)
        if _UUID_RE.fullmatch(candidate):
            continue
        if uuid_match and candidate in uuid_match.group(0):
            continue
        if best is None or len(candidate) > len(best):
            best = candidate
    return best


def build_order_status_href(status_token: str | None = None) -> str:
    base = "/orders/status"
    if not status_token:
        return base
    return f"{base}?token={quote(status_token, safe='')}"


def is_greeting_intent(message: str) -> bool:
    text = (message or "").strip()
    if not text or len(text) > 48:
        return False
    lowered = text.lower()
    folded = _ascii_fold(lowered)
    if any(
        marker == lowered
        or marker == folded
        or (len(marker) > 3 and (lowered.startswith(marker) or folded.startswith(marker)))
        for marker in _GREETING_OR_CHITCHAT
    ):
        return True
    return lowered in {"hi", "hey", "alo", "hello", "help"}


def try_greeting_reply(message: str) -> str | None:
    if not is_greeting_intent(message):
        return None
    lowered = (message or "").lower()
    folded = _ascii_fold(lowered)
    if "cam on" in folded or "cảm ơn" in lowered or "thank" in lowered:
        return "Không có chi! Bạn cần hỗ trợ gì thêm cứ nhắn mình nhé."
    return (
        "Chào bạn! Bạn có thể hỏi: shop bán gì, món nào bán chạy, chính sách giao hàng.\n"
        "Hoặc mở nhanh: [Xem sản phẩm](/products) · [Giỏ hàng](/cart) · [Tra cứu đơn](/orders/status)"
    )


def is_meta_chitchat_intent(message: str) -> bool:
    text = (message or "").strip()
    if not text or len(text) > 120:
        return False
    lowered = text.lower()
    folded = _ascii_fold(lowered)
    return any(marker in lowered or marker in folded for marker in _META_CHITCHAT_MARKERS)


def try_meta_chitchat_reply(message: str) -> str | None:
    if not is_meta_chitchat_intent(message):
        return None
    return (
        "Dạ, mình là trợ lý AI của shop — hỗ trợ xem món, giá và tra cứu đơn. "
        "Bạn cứ hỏi tự nhiên; cần người thật thì nhắn **gặp nhân viên**."
    )


def is_faq_only_intent(message: str) -> bool:
    lowered = (message or "").lower()
    folded = _ascii_fold(lowered)
    return any(marker in lowered or marker in folded for marker in _FAQ_ONLY_MARKERS)


def is_order_intent(message: str) -> bool:
    if is_catalog_recommend_intent(message):
        return False
    lowered = (message or "").lower()
    folded = _ascii_fold(lowered)
    return any(marker in lowered or marker in folded for marker in _ORDER_MARKERS)


def is_order_track_intent(message: str) -> bool:
    if extract_order_status_token_from_text(message):
        return True
    lowered = (message or "").lower().strip()
    folded = _ascii_fold(lowered)
    if extract_product_id_from_text(message):
        track_cues = ("don", "đơn", "order", "tra", "theo", "track", "status")
        if any(cue in lowered or cue in folded for cue in track_cues):
            return True
    return any(marker in lowered or marker in folded for marker in _ORDER_TRACK_MARKERS)


def is_catalog_recommend_intent(message: str) -> bool:
    lowered = (message or "").lower().strip()
    folded = _ascii_fold(lowered)
    return any(marker in lowered or marker in folded for marker in _CATALOG_RECOMMEND_MARKERS)


def is_catalog_browse_intent(message: str) -> bool:
    if is_catalog_recommend_intent(message):
        return False
    lowered = (message or "").lower().strip()
    folded = _ascii_fold(lowered)
    return any(marker in lowered or marker in folded for marker in _CATALOG_BROWSE_MARKERS)


def is_cart_view_intent(message: str) -> bool:
    if is_order_intent(message):
        return False
    lowered = (message or "").lower().strip()
    folded = _ascii_fold(lowered)
    if any(marker in lowered or marker in folded for marker in _CART_VIEW_MARKERS):
        return True
    return lowered in {"giỏ hàng", "gio hang", "cart"} or folded in {"gio hang", "cart"}


def is_product_search_intent(message: str) -> bool:
    text = (message or "").strip()
    if not text or is_meta_chitchat_intent(text):
        return False
    if (
        is_catalog_recommend_intent(text)
        or is_catalog_browse_intent(text)
        or is_faq_only_intent(text)
        or is_order_intent(text)
        or is_cart_view_intent(text)
        or is_order_track_intent(text)
        or is_greeting_intent(text)
    ):
        return False
    lowered = text.lower()
    folded = _ascii_fold(lowered)
    search_markers = ("co ", "có ", "con ", "còn ", "ban ", "bán ", "tim ", "tìm ")
    if any(marker in lowered or marker in folded for marker in search_markers):
        return True
    if extract_product_id_from_text(text):
        return True
    return len(text.split()) >= 2 and len(text) <= 80


def product_link_markdown(item_id: str, label: str) -> str:
    safe_label = (label or "Sản phẩm").strip() or "Sản phẩm"
    return f"[{safe_label}](/products/{item_id})"


def format_catalog_browse_reply(items: list[dict], *, max_items: int = 6) -> str:
    if not items:
        return (
            "Hiện shop chưa có sản phẩm nào hiển thị. "
            "Bạn quay lại sau hoặc hỏi món cụ thể nhé!"
        )
    shown = items[:max_items]
    lines = ["Dạ, shop đang có các món sau:"]
    for item in shown:
        name = (item.get("name") or "Sản phẩm").strip()
        item_id = item.get("id")
        sale = item.get("sale_price")
        regular = item.get("regular_price")
        unit = sale if sale is not None else regular
        price_note = f" — {unit:,.0f}đ" if unit is not None else ""
        if item_id:
            lines.append(f"• {product_link_markdown(str(item_id), name)}{price_note}")
        else:
            lines.append(f"• {name}{price_note}")
    lines.append("Bạn muốn xem giá hoặc đặt món nào cứ nhắn mình nhé!")
    return "\n".join(lines)


def format_bestseller_reply(items: list[dict], *, days: int = 30, max_items: int = 6) -> str:
    if not items:
        return (
            f"Dạ, {days} ngày qua shop chưa có đơn WEB nào đủ để thống kê bán chạy. "
            "Bạn xem menu hoặc hỏi tên món cụ thể nhé!"
        )
    shown = items[:max_items]
    lines = [f"Dạ, {days} ngày qua các món được order nhiều nhất:"]
    for item in shown:
        name = (item.get("name") or "Sản phẩm").strip()
        item_id = item.get("id")
        sale = item.get("sale_price")
        regular = item.get("regular_price")
        unit = sale if sale is not None else regular
        price_note = f" — {unit:,.0f}đ" if unit is not None else ""
        qty_sum = item.get("qty_sum")
        stat = f" ({int(qty_sum)} lượt ordered)" if qty_sum else ""
        if item_id:
            lines.append(f"• {product_link_markdown(str(item_id), name)}{price_note}{stat}")
        else:
            lines.append(f"• {name}{price_note}{stat}")
    lines.append("Bạn muốn xem giá hoặc đặt món nào cứ nhắn mình nhé!")
    return "\n".join(lines)


def format_product_search_vi(payload: dict) -> str:
    items = payload.get("items") or []
    if not items:
        return "Mình chưa tìm thấy món phù hợp. Bạn thử gõ tên món khác hoặc hỏi **shop bán gì** nhé."
    lines = [f"Dạ, mình tìm thấy {len(items)} món:"]
    for item in items:
        name = (item.get("name") or "Sản phẩm").strip()
        item_id = item.get("id")
        sale = item.get("sale_price")
        regular = item.get("regular_price")
        unit = sale if sale is not None else regular
        price_note = f" — {unit:,.0f}đ" if unit is not None else ""
        if item_id:
            lines.append(f"• {product_link_markdown(str(item_id), name)}{price_note}")
        else:
            lines.append(f"• {name}{price_note}")
    return "\n".join(lines)
