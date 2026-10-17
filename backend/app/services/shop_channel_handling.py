"""Live-agent handling modes for shop CSKH (widget + channels)."""

from __future__ import annotations

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


def handoff_reply_for_platform(platform: str) -> str:
    channel = (platform or "").strip().lower()
    if channel == "zalo":
        return f"{HANDOFF_REPLY_VI} (Zalo)"
    if channel == "messenger":
        return f"{HANDOFF_REPLY_VI} (Messenger)"
    return HANDOFF_REPLY_VI
