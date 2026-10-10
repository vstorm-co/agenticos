"""A pressed inline button on a Telegram message (#2064, #2068).

Apart from the adapter so the webhook route can read a press without importing
aiogram - which the app keeps out of its own import (#520).
"""

from typing import Any

from app.services.channels.base import IncomingPress


def parse_press(raw_payload: dict[str, Any], bot_id: str) -> IncomingPress | None:
    """A pressed inline button, from a webhook update or a polled one."""
    query = raw_payload.get("callback_query")
    if not isinstance(query, dict) or not isinstance(query.get("data"), str):
        return None
    message = query.get("message") or {}
    sender = query.get("from") or {}
    return IncomingPress(
        platform="telegram",
        bot_id=bot_id,
        platform_user_id=str(sender.get("id", "")),
        platform_chat_id=str((message.get("chat") or {}).get("id", "")),
        value=query["data"],
        platform_username=sender.get("username"),
        message_id=str(message["message_id"]) if "message_id" in message else None,
        prompt_text=message.get("text"),
        ack_id=str(query.get("id", "")) or None,
    )
