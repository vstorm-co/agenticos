"""Authenticate a company Mac bridge before handing messages to the shared router."""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from pydantic import JsonValue, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import spawn_after_commit
from app.core.exceptions import AuthorizationError, BadRequestError
from app.services.channel_bot import ChannelBotService, unseal_webhook_secret
from app.services.channels import get_adapter, sms_prompts
from app.services.channels.base import IncomingPress
from app.worker.background.channel import process_channel_event, process_channel_press

_PAYLOAD = TypeAdapter(dict[str, JsonValue])
_MAX_BYTES = 256 * 1024


class ImessageWebhookService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def receive(self, bot_id: UUID, authorization: str, chunks: AsyncIterator[bytes]) -> None:
        bot = await ChannelBotService(self._db).find_active(bot_id)
        if bot is None or bot.platform != "imessage" or not bot.webhook_mode:
            raise AuthorizationError(message="Invalid iMessage webhook credential")
        secret = unseal_webhook_secret(bot)
        adapter = get_adapter("imessage")
        if secret is None or not adapter.verify_webhook_signature(
            {"authorization": authorization}, secret
        ):
            raise AuthorizationError(message="Invalid iMessage webhook credential")
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in chunks:
                    if len(body) + len(chunk) > _MAX_BYTES:
                        raise BadRequestError(message="The iMessage webhook exceeds 256 KiB")
                    body.extend(chunk)
        except TimeoutError:
            raise BadRequestError(message="The iMessage webhook body timed out") from None
        try:
            payload = _PAYLOAD.validate_json(body)
        except ValidationError:
            raise BadRequestError(
                message="The iMessage webhook must contain a JSON object"
            ) from None
        incoming = adapter.parse_incoming(payload, str(bot_id))
        if incoming is None:
            return
        choice = (
            await sms_prompts.answer(
                str(bot_id), incoming.platform_chat_id, incoming.text, platform="imessage"
            )
            if not incoming.attachments
            else None
        )
        if choice is not None:
            press = IncomingPress(
                platform="imessage",
                bot_id=str(bot_id),
                platform_user_id=incoming.platform_user_id,
                platform_chat_id=incoming.platform_chat_id,
                value=choice,
                message_id=incoming.message_id,
            )
            spawn_after_commit(
                self._db, process_channel_press(press), name=f"imessage_press:{bot_id}"
            )
        else:
            spawn_after_commit(
                self._db, process_channel_event(incoming), name=f"imessage_event:{bot_id}"
            )
