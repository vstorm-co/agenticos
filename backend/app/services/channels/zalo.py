"""Zalo Official Account channel adapter (D3 B68 — shop CSKH ingress)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services.channels.base import ChannelAdapter, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

ZALO_OA_MESSAGE_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"


class ZaloAdapter(ChannelAdapter):
    """Zalo OA webhook ingress + outbound message API."""

    platform: str = "zalo"

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        payload = {
            "recipient": {"user_id": msg.platform_chat_id},
            "message": {"text": msg.text},
        }
        headers = {"access_token": bot_token, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(ZALO_OA_MESSAGE_URL, json=payload, headers=headers)
        if response.status_code != 200:
            logger.error("Zalo send failed: %s %s", response.status_code, response.text[:300])
            response.raise_for_status()

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        logger.info("Zalo bot %s: webhook mode only (polling skipped)", bot_id)

    async def stop_polling(self, bot_id: str) -> None:
        return None

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        logger.info(
            "Zalo OA webhook must be registered manually in Zalo Developer Console: %s",
            url,
        )
        return True

    async def delete_webhook(self, bot_token: str) -> bool:
        logger.info("Remove Zalo OA webhook manually in Zalo Developer Console if needed")
        return True

    @staticmethod
    def _normalize_signature(received: str) -> str:
        value = received.strip().lower()
        if value.startswith("mac="):
            return value[4:]
        return value

    @staticmethod
    def _sha256_event_mac(app_id: str, body: str, timestamp: str, secret: str) -> str:
        return hashlib.sha256(f"{app_id}{body}{timestamp}{secret}".encode()).hexdigest()

    @staticmethod
    def _hmac_body_mac(body: str, secret: str) -> str:
        return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        if not secret or not body or not body.strip():
            return False
        received_raw = headers.get("x-zevent-signature", headers.get("X-ZEvent-Signature", "")).strip()
        if not received_raw:
            return False
        provided = self._normalize_signature(received_raw)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict):
            return False

        app_ids: list[str] = []
        for candidate in (
            data.get("app_id"),
            settings.ZALO_OA_APP_ID,
        ):
            if candidate is None:
                continue
            value = str(candidate).strip()
            if value and value not in app_ids:
                app_ids.append(value)
        expected_hmac = self._hmac_body_mac(body, secret)
        if hmac.compare_digest(provided, expected_hmac.lower()):
            return True

        timestamps: list[str] = []
        header_ts = (
            headers.get("x-zevent-timestamp", headers.get("X-ZEvent-Timestamp", "")) or ""
        ).strip()
        if header_ts:
            timestamps.append(header_ts)
        body_ts = data.get("timestamp")
        if body_ts is not None:
            body_ts_str = str(body_ts).strip()
            if body_ts_str and body_ts_str not in timestamps:
                timestamps.append(body_ts_str)
        if not app_ids or not timestamps:
            return False

        for app_id in app_ids:
            for timestamp in timestamps:
                expected = self._sha256_event_mac(app_id, body, timestamp, secret)
                if hmac.compare_digest(provided, expected.lower()):
                    return True

        return False

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        event_name = raw_payload.get("event_name") or raw_payload.get("event")
        if event_name != "user_send_text":
            return None

        message = raw_payload.get("message") or {}
        text = message.get("text") if isinstance(message, dict) else None
        if not text and isinstance(raw_payload.get("message"), str):
            text = raw_payload["message"]
        if not text:
            return None

        sender = raw_payload.get("sender") or {}
        platform_user_id = str(sender.get("id", ""))
        if not platform_user_id:
            return None

        platform_chat_id = platform_user_id
        display_name = sender.get("name") or platform_user_id

        return IncomingMessage(
            platform="zalo",
            bot_id=bot_id,
            platform_user_id=platform_user_id,
            platform_chat_id=platform_chat_id,
            chat_type="private",
            text=str(text),
            raw=raw_payload,
            platform_username=None,
            platform_display_name=str(display_name),
            message_id=str(message.get("msg_id")) if isinstance(message, dict) else None,
        )
