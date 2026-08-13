"""Telegram channel adapter using aiogram v3."""

import asyncio
import contextlib
import hmac
import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message as AiogramMessage

from app.agents.capabilities.channel_tools import ChannelDetails, ChannelMember
from app.db.session import get_db_context
from app.services.channels.base import (
    ChannelAdapter,
    IncomingAttachment,
    IncomingMessage,
    OutgoingMessage,
)
from app.services.channels.router import ChannelMessageRouter

logger = logging.getLogger(__name__)


# Every field Telegram puts a file in, with a name and a type for the kinds that
# arrive without one. A voice note has neither: it is `voice.ogg` by convention and
# `audio/ogg` by format, and inventing them here is better than storing a file
# nothing downstream can identify.
_MEDIA_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("document", "file", "application/octet-stream"),
    ("voice", "voice.ogg", "audio/ogg"),
    ("audio", "audio", "audio/mpeg"),
    ("video", "video.mp4", "video/mp4"),
    ("video_note", "video-note.mp4", "video/mp4"),
)


class TelegramAdapter(ChannelAdapter):
    """Concrete Telegram adapter using aiogram v3."""

    platform: str = "telegram"

    def __init__(self) -> None:
        self._polling_tasks: dict[str, asyncio.Task[None]] = {}

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Send the message that will become the answer, and return its id."""
        bot = Bot(token=bot_token)
        try:
            sent = await bot.send_message(
                chat_id=msg.platform_chat_id,
                text=msg.text,
                reply_to_message_id=int(msg.reply_to_message_id)
                if msg.reply_to_message_id
                else None,
            )
        finally:
            await bot.session.close()
        return str(sent.message_id)

    async def update_reply(self, bot_token: str, msg: OutgoingMessage, handle: str) -> None:
        """Rewrite a message already in the chat.

        No parse mode: half-written Markdown is the normal state of a message
        being streamed, and Telegram rejects an unclosed `**` with a 400. The
        final send formats it, once the text is whole.
        """
        bot = Bot(token=bot_token)
        try:
            await bot.edit_message_text(
                chat_id=msg.platform_chat_id, message_id=int(handle), text=msg.text
            )
        finally:
            await bot.session.close()

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

    #
    # Two of the four, and that is the whole of what Telegram gives a bot.
    # `search_channels` and `channel_history` are inherited from the base class,
    # which refuses with a sentence: Telegram has no directory of chats to
    # search, and a bot receives messages rather than reading them back - there
    # is no `getChatHistory`, and the closest thing needs a *user* account.
    # Answering those two with empty lists would read as "there is nothing
    # there", which is a different and wrong statement.

    async def channel_details(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None
    ) -> ChannelDetails:
        """`getChat` and `getChatMemberCount`.

        A Telegram chat has a `description` and no separate topic, so `purpose`
        carries it and `topic` stays empty rather than repeating it.
        """
        bot = Bot(token=bot_token)
        try:
            chat = await bot.get_chat(chat_id=channel_id)
            count = await bot.get_chat_member_count(chat_id=channel_id)
        finally:
            await bot.session.close()

        return ChannelDetails(
            channel_id=str(chat.id),
            name=chat.title or chat.username or str(chat.id),
            purpose=chat.description or None,
            is_private=chat.type != "channel",
            member_count=count,
        )

    async def channel_members(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None, limit: int
    ) -> list[ChannelMember]:
        """`getChatAdministrators` - which is as far as a bot can see.

        Telegram gives a bot no way to enumerate ordinary members of a group,
        deliberately. So this returns the administrators, and every row says
        `admin` in its role: a list that quietly stopped at the administrators
        while reading as "everybody here" would have the model tell somebody
        their colleague is not in the chat.
        """
        bot = Bot(token=bot_token)
        try:
            administrators = await bot.get_chat_administrators(chat_id=channel_id)
        finally:
            await bot.session.close()

        return [
            ChannelMember(
                user_id=str(entry.user.id),
                username=entry.user.username,
                display_name=entry.user.full_name,
                is_bot=entry.user.is_bot,
                role="admin",
            )
            for entry in administrators[:limit]
        ]

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
        return hmac.compare_digest(received.encode(), secret.encode())

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """Normalise one Telegram update, whichever transport delivered it.

        The webhook receiver and the polling loop both arrive here, so the rules
        about what counts as a message are stated once. They were stated twice
        until #547, and the copies disagreed about files.

        `message` and `edited_message` only. A file with no caption is a message;
        a message with no sender is not. The Bot API leaves `from` empty for a
        message sent to a channel, and a run has to be somebody's - answering one
        would key a single shared identity on an empty user id. A post made on
        behalf of a chat elsewhere carries a stand-in sender rather than nothing,
        so this refuses less than it sounds like: it refuses the case where there
        is genuinely nobody to link the run to.
        """
        msg_data: dict[str, Any] | None = raw_payload.get("message") or raw_payload.get(
            "edited_message"
        )

        if not msg_data:
            return None

        from_user: dict[str, Any] = msg_data.get("from") or {}
        if not from_user.get("id"):
            return None

        attachments = self._attachments(msg_data)
        text: str = msg_data.get("text") or msg_data.get("caption") or ""
        if not text and not attachments:
            return None

        chat = msg_data.get("chat", {})

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

        Telegram does not put files in one list. Each kind is its own field, and a
        message carrying only one of them has no text at all - which is why a voice
        note used to parse as nothing and vanish without a log line. Every kind it
        can send is read here, and one it cannot yet do anything with is refused
        further down *by name* rather than dropped.

        A `photo` arrives as the same image in several sizes and the last is the
        largest, which is the one worth having - the rest are thumbnails Telegram
        generated. It also sends no MIME type for one, so a JPEG is stated rather
        than guessed from bytes nobody has yet.
        """
        found: list[IncomingAttachment] = []

        for field, fallback_name, fallback_mime in _MEDIA_FIELDS:
            media = msg_data.get(field)
            if not isinstance(media, dict) or not media.get("file_id"):
                continue
            found.append(
                IncomingAttachment(
                    filename=media.get("file_name") or fallback_name,
                    mime_type=media.get("mime_type") or fallback_mime,
                    size=int(media.get("file_size") or 0),
                    handle=str(media["file_id"]),
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
        """Route one update from the polling loop, through the one parser.

        aiogram has already decoded what Telegram POSTs to the webhook receiver,
        so the update is put back into that shape and normalised by
        `parse_incoming` rather than by a second copy of it - which is what this
        was, and the copy read no files (#547): a spreadsheet dropped on a bot in
        polling mode, the mode a self-hosted deployment runs, was discarded and
        the agent answered about a document it never received.

        `by_alias` because the Bot API's `from` is a Python keyword and aiogram
        renames it - without it nothing here finds a sender and every polled
        message is refused. `exclude_none` because Telegram omits a field it has
        nothing for while aiogram holds a `None`: left in, a sender with no
        surname is displayed as "Ada None".

        Only `message` reaches this. `@dp.message()` is the sole handler, so
        aiogram asks Telegram for that update type alone and an edit is never
        delivered - unlike the webhook receiver, which is sent whatever the
        platform has and reads `edited_message` too.
        """
        incoming = self.parse_incoming(
            {"message": message.model_dump(mode="json", by_alias=True, exclude_none=True)}, bot_id
        )
        if incoming is None:
            return

        router = ChannelMessageRouter()

        async with get_db_context() as db:
            await router.route(incoming, db)
