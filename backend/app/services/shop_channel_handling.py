"""Live-agent handling modes for shop CSKH (widget + channels)."""

from __future__ import annotations

import re
import unicodedata

HANDLING_MODE_AI = "ai"
HANDLING_MODE_QUEUED = "queued"
HANDLING_MODE_HUMAN = "human"

STAFF_MESSAGE_MODEL = "staff"

HANDOFF_REPLY_VI = (
    "Shop đang chuyển bạn tới nhân viên CSKH. "
    "Vui lòng chờ trong giây lát — nhân viên sẽ trả lời trực tiếp."
)

QUEUED_USER_ACK_VI = (
    "Tin nhắn của bạn đã ghi nhận. Nhân viên CSKH sẽ trả lời trực tiếp tại đây."
)

LIVE_AGENT_ESCALATE_HINT_VI = (
    '\n\nCần gặp nhân viên? Gõ "gặp nhân viên" hoặc "human agent" để shop chuyển CS trực tiếp.'
)

_ESCALATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"gap\s+nhan\s+vien"),
    re.compile(r"nhan\s+vien"),
    re.compile(r"tu\s+van\s+vien"),
    re.compile(r"nguoi\s+that"),
    re.compile(r"live\s+agent"),
    re.compile(r"human\s+agent"),
    re.compile(r"chuyen\s+cskh"),
    re.compile(r"hotline"),
    re.compile(r"goi\s+(cho\s+)?shop\b"),
    re.compile(r"lien\s+he\s+(shop|cskh|cs\b)"),
    re.compile(r"chat\s+voi\s+(cs|cskh|shop)\b"),
    re.compile(r"gap\s+(cskh|cs\b)"),
    re.compile(r"co\s+(ai|nguoi)\s+khong"),
    re.compile(r"noi\s+chuyen\s+voi\s+shop\b"),
    re.compile(r"ho\s+tro\s+(truc\s+tiep|nhan\s+vien)"),
    re.compile(r"tu\s+van\s+truc\s+tiep"),
)


def _normalize(text: str) -> str:
    lowered = text.casefold().strip()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def wants_human_agent(message: str) -> bool:
    normalized = _normalize(message)
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _ESCALATION_PATTERNS)


def shop_cskh_welcome_message(bot_name: str, custom: str | None = None) -> str:
    name = (bot_name or "Shop").strip() or "Shop"
    base = (custom or "").strip() or (
        f"Xin chào! Em là {name} — trợ lý shop. Em có thể giúp gì ạ?"
    )
    if LIVE_AGENT_ESCALATE_HINT_VI.strip() in base:
        return base
    return base + LIVE_AGENT_ESCALATE_HINT_VI


def append_live_agent_escalate_hint(text: str) -> str:
    body = (text or "").strip()
    hint = LIVE_AGENT_ESCALATE_HINT_VI.strip()
    if not body:
        return hint
    if hint in body:
        return body
    return body + LIVE_AGENT_ESCALATE_HINT_VI


def handoff_reply_for_platform(platform: str) -> str:
    channel = (platform or "").strip().lower()
    if channel == "zalo":
        return f"{HANDOFF_REPLY_VI} (Zalo)"
    if channel == "messenger":
        return f"{HANDOFF_REPLY_VI} (Messenger)"
    return HANDOFF_REPLY_VI
