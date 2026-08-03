"""Telegram channel adapter using aiogram v3."""

import asyncio
import contextlib
import hmac
import logging
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message as AiogramMessage

from app.db.session import get_db_context
from app.services.channels.base import (
    ChannelAdapter,
    IncomingAttachment,
    IncomingMessage,
    OutgoingMessage,
)
from app.services.channels.router import ChannelMessageRouter

logger = logging.getLogger(__name__)

_telegram_router = Router()


class TelegramAdapter(ChannelAdapter):
    """Concrete Telegram adapter using aiogram v3."""

    platform: str = "telegram"

    def __init__(self) -> None:
        self._polling_tasks: dict[str, asyncio.Task[None]] = {}

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Send a reply back to Telegram.

        Tries Markdown parse mode first; falls back to plain text if
        Telegram rejects the formatting (common with LLM-generated markdown).
        """
        bot = Bot(
            token=bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        reply_to = int(msg.reply_to_message_id) if msg.reply_to_message_id else None
        try:
            if msg.image_png is not None:
                from aiogram.types import BufferedInputFile

                await bot.send_photo(
                    chat_id=msg.platform_chat_id,
                    photo=BufferedInputFile(msg.image_png, filename=msg.image_filename),
                    caption=msg.text,
                    reply_to_message_id=reply_to,
                )
                return
            if msg.attachments:
                await self._send_documents(bot, msg, reply_to)
                return
            try:
                await bot.send_message(
                    chat_id=msg.platform_chat_id,
                    text=msg.text,
                    parse_mode=msg.parse_mode,  # type: ignore[arg-type]
                    reply_to_message_id=reply_to,
                )
            except TelegramBadRequest:
                # Markdown parsing failed - send as plain text
                await bot.send_message(
                    chat_id=msg.platform_chat_id,
                    text=msg.text,
                    parse_mode=None,
                    reply_to_message_id=reply_to,
                )
        finally:
            await bot.session.close()

    @staticmethod
    async def _send_documents(bot: Bot, msg: OutgoingMessage, reply_to: int | None) -> None:
        """Post the files, with the text as the first one's caption.

        The caption rides on the first document rather than being sent as its own
        message, so the answer and the file it is about arrive together. Telegram
        caps a caption at 1024 characters, so a longer answer is sent as a message
        first and the files follow - truncating an agent's answer to fit a caption
        would lose the part somebody asked for.
        """
        from aiogram.types import BufferedInputFile

        caption: str | None = msg.text if len(msg.text) <= 1024 else None
        if caption is None:
            try:
                await bot.send_message(
                    chat_id=msg.platform_chat_id, text=msg.text, reply_to_message_id=reply_to
                )
            except TelegramBadRequest:
                await bot.send_message(
                    chat_id=msg.platform_chat_id,
                    text=msg.text,
                    parse_mode=None,
                    reply_to_message_id=reply_to,
                )

        for index, attachment in enumerate(msg.attachments):
            await bot.send_document(
                chat_id=msg.platform_chat_id,
                document=BufferedInputFile(attachment.content, filename=attachment.filename),
                caption=caption if index == 0 else None,
                reply_to_message_id=reply_to,
            )

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """Start a supervised polling loop for this bot."""
        if bot_id in self._polling_tasks and not self._polling_tasks[bot_id].done():
            logger.info("Polling already running for bot %s", bot_id)
            return

        task = asyncio.create_task(
            self._polling_supervisor(bot_id, bot_token),
            name=f"telegram_polling_{bot_id}",
        )
        self._polling_tasks[bot_id] = task
        logger.info("Started Telegram polling for bot %s", bot_id)

    async def stop_polling(self, bot_id: str) -> None:
        """Cancel the polling task for this bot."""
        task = self._polling_tasks.pop(bot_id, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("Stopped Telegram polling for bot %s", bot_id)

    async def _polling_supervisor(self, bot_id: str, bot_token: str) -> None:
        """Supervised loop: restart polling on crash, stop on CancelledError."""
        while True:
            try:
                await self._run_polling_once(bot_id, bot_token)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Telegram polling crashed for bot %s, restarting in 5s", bot_id)
                await asyncio.sleep(5)

    async def _run_polling_once(self, bot_id: str, bot_token: str) -> None:
        """Run one polling session using aiogram Dispatcher."""
        bot = Bot(
            token=bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        dp = Dispatcher()

        @dp.message()
        async def on_message(message: AiogramMessage) -> None:
            await self._handle_update(message, bot_id)

        try:
            await dp.start_polling(bot, handle_signals=False)
        finally:
            await bot.session.close()

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """Register a webhook URL with Telegram."""
        bot = Bot(token=bot_token)
        try:
            await bot.set_webhook(url=url, secret_token=secret)
            return True
        except Exception:
            logger.exception("Failed to register Telegram webhook")
            return False
        finally:
            await bot.session.close()

    async def delete_webhook(self, bot_token: str) -> bool:
        """Remove the webhook from Telegram."""
        bot = Bot(token=bot_token)
        try:
            await bot.delete_webhook()
            return True
        except Exception:
            logger.exception("Failed to delete Telegram webhook")
            return False
        finally:
            await bot.session.close()

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """Verify that the request came from Telegram via the secret token header.

        The `body` parameter is unused for Telegram (signature is header-only)
        but accepted for interface compatibility with ChannelAdapter.
        """
        received = headers.get("x-telegram-bot-api-secret-token", "")
        # Use hmac.compare_digest for constant-time comparison
        return hmac.compare_digest(received.encode(), secret.encode())

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """Parse a Telegram update payload into IncomingMessage.

        Handles `message` and `edited_message` update types; text only (V1).
        Returns None for non-text updates.
        """
        msg_data: dict[str, Any] | None = raw_payload.get("message") or raw_payload.get(
            "edited_message"
        )

        if not msg_data:
            return None

        attachments = self._attachments(msg_data)
        text: str = msg_data.get("text") or msg_data.get("caption") or ""
        if not text and not attachments:
            return None

        chat = msg_data.get("chat", {})
        from_user = msg_data.get("from", {})

        chat_type: str = chat.get("type", "private")
        platform_chat_id: str = str(chat.get("id", ""))
        platform_user_id: str = str(from_user.get("id", ""))

        username: str | None = from_user.get("username")
        first_name: str = from_user.get("first_name", "")
        last_name: str = from_user.get("last_name", "")
        display_name: str = f"{first_name} {last_name}".strip() or username or platform_user_id

        message_id: str | None = str(msg_data["message_id"]) if "message_id" in msg_data else None

        return IncomingMessage(
            platform="telegram",
            bot_id=bot_id,
            platform_user_id=platform_user_id,
            platform_chat_id=platform_chat_id,
            chat_type=chat_type,
            text=text,
            raw=raw_payload,
            platform_username=username,
            platform_display_name=display_name,
            message_id=message_id,
            attachments=attachments,
        )

    @staticmethod
    def _attachments(msg_data: dict[str, Any]) -> list[IncomingAttachment]:
        """The files on a Telegram message, as handles.

        `document` is the ordinary case. A `photo` arrives as a list of the same
        image in several sizes and the last is the largest, which is the one worth
        having - the others are thumbnails Telegram generated.

        Telegram sends no MIME type for a photo, so one is stated rather than
        guessed from bytes we do not have yet: every entry in `photo` is a JPEG.
        """
        found: list[IncomingAttachment] = []

        document = msg_data.get("document")
        if isinstance(document, dict) and document.get("file_id"):
            found.append(
                IncomingAttachment(
                    filename=document.get("file_name") or "file",
                    mime_type=document.get("mime_type") or "application/octet-stream",
                    size=int(document.get("file_size") or 0),
                    handle=str(document["file_id"]),
                )
            )

        photos = msg_data.get("photo")
        if isinstance(photos, list) and photos:
            largest = photos[-1]
            found.append(
                IncomingAttachment(
                    filename=f"photo-{largest.get('file_unique_id', 'image')}.jpg",
                    mime_type="image/jpeg",
                    size=int(largest.get("file_size") or 0),
                    handle=str(largest.get("file_id", "")),
                )
            )

        return found

    async def download_attachment(self, bot_token: str, attachment: IncomingAttachment) -> bytes:
        """Fetch a file: `getFile` for the path, then the file API for the bytes.

        Two requests because that is Telegram's design - a `file_id` is not a URL
        and the path it resolves to expires - so resolving it at parse time would
        hand the router a link that had gone stale by the time anybody used it.
        """
        bot = Bot(token=bot_token)
        try:
            info = await bot.get_file(attachment.handle)
            if info.file_path is None:
                raise ValueError(f"Telegram returned no path for {attachment.filename}")
            buffer = await bot.download_file(info.file_path)
            if buffer is None:
                raise ValueError(f"Telegram returned no bytes for {attachment.filename}")
            return buffer.read()
        finally:
            await bot.session.close()

    async def _handle_update(self, message: AiogramMessage, bot_id: str) -> None:
        """Handle an incoming aiogram Message inside the polling loop."""
        if not message.text:
            return

        chat = message.chat
        from_user = message.from_user

        if from_user is None:
            return

        chat_type: str = chat.type.value if hasattr(chat.type, "value") else str(chat.type)

        incoming = IncomingMessage(
            platform="telegram",
            bot_id=bot_id,
            platform_user_id=str(from_user.id),
            platform_chat_id=str(chat.id),
            chat_type=chat_type,
            text=message.text,
            raw={},
            platform_username=from_user.username,
            platform_display_name=from_user.full_name,
            message_id=str(message.message_id),
        )

        router = ChannelMessageRouter()

        async with get_db_context() as db:
            await router.route(incoming, db)
