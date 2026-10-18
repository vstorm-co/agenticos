"""Facebook Messenger channel adapter (D3 B69)."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.services.channels.base import ChannelAdapter, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

MESSENGER_SEND_URL = "https://graph.facebook.com/v21.0/me/messages"


class MessengerAdapter(ChannelAdapter):
    """Facebook Page Messenger — webhook ingress + Graph send API."""

    platform: str = "messenger"

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        payload = {
            "recipient": {"id": msg.platform_chat_id},
            "message": {"text": msg.text[:2000]},
        }
        params = {"access_token": bot_token}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(MESSENGER_SEND_URL, json=payload, params=params)
        if response.status_code != 200:
            logger.error(
                "Messenger send failed: %s %s",
                response.status_code,
                response.text[:300],
            )
            response.raise_for_status()

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        logger.info("Messenger bot %s: webhook mode only (polling skipped)", bot_id)

    async def stop_polling(self, bot_id: str) -> None:
        return None

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        logger.info(
            "Messenger webhook must be configured in Meta Developer Console: %s",
            url,
        )
        return True

    async def delete_webhook(self, bot_token: str) -> bool:
        logger.info("Remove Messenger webhook in Meta Developer Console if needed")
        return True

    @staticmethod
    def verify_webhook_signature(
        headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        if not secret or not body:
            return False
        received = (
            headers.get("x-hub-signature-256", headers.get("X-Hub-Signature-256", "")) or ""
        ).strip()
        if not received.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(received[7:], expected)

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        if raw_payload.get("object") != "page":
            return None
        for entry in raw_payload.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            for event in entry.get("messaging") or []:
                if not isinstance(event, dict):
                    continue
                message = event.get("message") or {}
                if not isinstance(message, dict):
                    continue
                if message.get("is_echo"):
                    continue
                text = message.get("text")
                if not text or not str(text).strip():
                    continue
                sender = event.get("sender") or {}
                platform_user_id = str(sender.get("id", "")).strip()
                if not platform_user_id:
                    continue
                return IncomingMessage(
                    platform="messenger",
                    bot_id=bot_id,
                    platform_user_id=platform_user_id,
                    platform_chat_id=platform_user_id,
                    chat_type="private",
                    text=str(text).strip(),
                    raw=event,
                    platform_username=None,
                    platform_display_name=platform_user_id,
                    message_id=str(message.get("mid")) if message.get("mid") else None,
                )
        return None
