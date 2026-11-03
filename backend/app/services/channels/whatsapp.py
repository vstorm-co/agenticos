"""WhatsApp, over Meta's Cloud API (#2076).

A bot is a WhatsApp Business number. Meta posts every message to
`/api/v1/whatsapp/{bot_id}/webhook`; the route checks the HMAC over the raw body
(`whatsapp_payload`) before a field is read, and this adapter answers through the
Graph client. Nothing is polled and no connection is held.

**What a customer is.** A business-scoped user id (BSUID), never a phone number:
it is the chat id answers go to, and `WhatsAppCredentials` - the bot's "token" in
the channel layer - carries the number the answer is sent from.

**Replies cannot be edited.** WhatsApp has no edit, so `begin_reply` answers
`None` and the router sends one finished message. What the customer sees while the
agent works is the read receipt and the typing indicator, which Meta shows for 25
seconds and which is re-sent until the answer goes out.
"""

import asyncio
import logging
from dataclasses import dataclass, replace
from typing import Any, Literal

from app.core.background import spawn
from app.core.config import settings
from app.services.channels import connection_state
from app.services.channels.base import (
    ChannelAdapter,
    IncomingAttachment,
    IncomingMessage,
    OutgoingMessage,
)
from app.services.channels.whatsapp_format import split_message, to_whatsapp, utf16_units
from app.services.channels.whatsapp_graph import (
    TOKEN_REFUSED,
    WhatsAppCredentials,
    WhatsAppGraph,
    WhatsAppGraphError,
    WhatsAppTokenRefused,
)
from app.services.channels.whatsapp_payload import verify_signature
from app.services.transcription import MAX_BYTES as TRANSCRIPTION_MAX_BYTES

logger = logging.getLogger(__name__)

TYPING_REFRESH_SECONDS: float = 20
"""Meta clears the indicator after 25 seconds; this re-sends it before that."""

TYPING_MAX_SECONDS: float = 300
"""A turn that has not answered by now is not going to; stop claiming it is typing."""

_sleep = asyncio.sleep
"""The refresher's clock, a name of its own so a test can advance it by hand."""

FILE_NOT_SENT = "(A file that came with this answer could not be sent.)"
"""Said instead of dropping a file silently when Meta refused its upload."""

CAPTION_MAX = 1024
"""Meta's limit on a caption, in characters."""

IMAGE_MAX_BYTES = 5 * 1024 * 1024
"""Meta shows a JPEG or PNG up to this size as a picture; anything else is a document."""

_IMAGE_TYPES = frozenset({"image/jpeg", "image/png"})


@dataclass(frozen=True)
class _Upload:
    media_id: str
    kind: Literal["image", "document"]
    filename: str


def _typing_failed(creds: WhatsAppCredentials | None, failure: Exception) -> None:
    """Log that the indicator failed: which bot and Graph's code, never the cause."""
    code = (
        (failure.details or {}).get("code")
        if isinstance(failure, WhatsAppGraphError | WhatsAppTokenRefused)
        else None
    )
    logger.warning(
        "whatsapp_typing_failed",
        extra={"bot_id": creds.bot_id if creds else None, "code": code},
    )


class WhatsAppAdapter(ChannelAdapter):
    platform = "whatsapp"

    def __init__(self, graph: WhatsAppGraph | None = None) -> None:
        self._graph = graph or WhatsAppGraph()
        self._typing: dict[tuple[str, str], asyncio.Task[Any]] = {}

    async def aclose(self) -> None:
        for key in list(self._typing):
            self._stop_typing(key)
        await self._graph.aclose()

    def _stop_typing(self, key: tuple[str, str]) -> None:
        task = self._typing.pop(key, None)
        if task is not None:
            task.cancel()

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Send the answer, then its chart and files, as WhatsApp messages.

        Every file is uploaded before anything is sent. A file Meta refuses
        (`WhatsAppGraphError`) is dropped and `FILE_NOT_SENT` is added to the
        answer once. A short answer (at most 1024 UTF-16 units) is the first file's
        caption and no text message is sent; a longer one goes first as text and
        the files follow without captions. When the only text is that note, it
        follows the files as a text message. The reply context goes on the first
        message actually sent.

        Raises:
            WhatsAppTokenRefused: Meta refused the access token; the bot is marked
                down in the console list until a send succeeds.
            WhatsAppGraphError: Any other refusal, or every file was refused and
                there was no text to send instead: the caller (`send_channel_file`)
                must not report a delivery that did not happen.
        """
        creds = WhatsAppCredentials.decode(bot_token)
        self._stop_typing((creds.bot_id, msg.platform_chat_id))
        text = to_whatsapp(msg.text).strip()
        reply_to = msg.reply_to_message_id
        try:
            uploads, refusal = await self._upload_all(creds, msg)
            if refusal is not None and not uploads and not text:
                raise refusal
            note_only = refusal is not None and not text
            if refusal is not None:
                text = f"{text}\n\n{FILE_NOT_SENT}" if text else FILE_NOT_SENT
            # A short answer rides on the first file as its caption: one message,
            # and the picture arrives with its explanation.
            caption = (
                text
                if uploads and text and not note_only and utf16_units(text) <= CAPTION_MAX
                else None
            )
            if caption is None and not note_only:
                reply_to = await self._send_text(creds, msg.platform_chat_id, text, reply_to)
            for upload in uploads:
                await self._graph.send_media(
                    creds,
                    recipient=msg.platform_chat_id,
                    kind=upload.kind,
                    media_id=upload.media_id,
                    caption=caption,
                    filename=upload.filename,
                    reply_to=reply_to,
                )
                caption = reply_to = None
            if note_only:
                await self._send_text(creds, msg.platform_chat_id, text, reply_to)
        except WhatsAppTokenRefused:
            await connection_state.record_down(creds.bot_id, TOKEN_REFUSED)
            raise
        # Read from the shared entry, not remembered here: the worker whose send
        # succeeds is rarely the one that saw the refusal.
        recorded = await connection_state.read(creds.bot_id)
        if recorded is not None and recorded.state == "down":
            await connection_state.record_up(creds.bot_id)

    async def _send_text(
        self, creds: WhatsAppCredentials, chat_id: str, text: str, reply_to: str | None
    ) -> str | None:
        """Send `text` in as many messages as its limit needs; the reply context goes first.

        Returns the reply context still unused: none when a message went out.
        """
        for chunk in split_message(text):
            await self._graph.send_text(creds, recipient=chat_id, body=chunk, reply_to=reply_to)
            reply_to = None
        return reply_to

    async def _upload_all(
        self, creds: WhatsAppCredentials, msg: OutgoingMessage
    ) -> tuple[list[_Upload], WhatsAppGraphError | None]:
        """Upload the chart and files before anything is sent; and the last refusal, if any.

        Uploading first means a refused file is known before the answer goes out,
        so the answer can say so. Only Graph's own refusals drop a file; a refused
        token propagates. Plain-text-like types go up as `text/plain`.
        """
        files = [(msg.image_filename, msg.image_png, "image/png")] if msg.image_png else []
        files += [(a.filename, a.content, a.mime_type) for a in msg.attachments]
        uploads: list[_Upload] = []
        refusal: WhatsAppGraphError | None = None
        for filename, content, mime_type in files:
            mime_type = mime_type.split(";")[0].strip().lower()
            if mime_type.startswith("text/") or mime_type == "application/json":
                # Meta's upload takes plain text but not CSV, Markdown or JSON; the
                # filename still tells the phone what the file is.
                mime_type = "text/plain"
            try:
                media_id = await self._graph.upload_media(
                    creds, content=content, mime_type=mime_type, filename=filename
                )
            except WhatsAppGraphError as failure:
                logger.warning(
                    "whatsapp_upload_failed",
                    extra={"bot_id": creds.bot_id, "code": (failure.details or {}).get("code")},
                )
                refusal = failure
                continue
            as_image = mime_type in _IMAGE_TYPES and len(content) <= IMAGE_MAX_BYTES
            uploads.append(_Upload(media_id, "image" if as_image else "document", filename))
        return uploads, refusal

    async def describe_attachments(
        self, bot_token: str, attachments: list[IncomingAttachment]
    ) -> list[IncomingAttachment]:
        """Fill in the size, and the type of an untyped file, from Meta.

        The webhook states neither size nor always a type. A handle that is not a
        media id (a message the parser could only name) is left alone, and so is
        an attachment whose lookup failed: the download then refuses it by name.
        """
        creds = WhatsAppCredentials.decode(bot_token)
        described: list[IncomingAttachment] = []
        for attachment in attachments:
            if not attachment.handle.isdigit():
                described.append(attachment)
                continue
            try:
                info = await self._graph.media_info(creds, media_id=attachment.handle)
            except (WhatsAppGraphError, WhatsAppTokenRefused) as failure:
                logger.warning(
                    "whatsapp_media_lookup_failed",
                    extra={"bot_id": creds.bot_id, "code": (failure.details or {}).get("code")},
                )
                described.append(attachment)
                continue
            mime_type = attachment.mime_type
            if mime_type == "application/octet-stream" and info.mime_type:
                mime_type = info.mime_type.split(";")[0].strip()
            described.append(replace(attachment, mime_type=mime_type, size=info.file_size or 0))
        return described

    async def download_attachment(self, bot_token: str, attachment: IncomingAttachment) -> bytes:
        """Fetch a customer's file; the lookup is repeated because Meta's URL lives 5 minutes."""
        creds = WhatsAppCredentials.decode(bot_token)
        info = await self._graph.media_info(creds, media_id=attachment.handle)
        limit = (
            TRANSCRIPTION_MAX_BYTES
            if attachment.mime_type.startswith("audio/")
            else settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
        )
        return await self._graph.download_media(creds, url=info.url, limit=limit)

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Mark the customer's message read and show "typing" until the answer is sent.

        Always `None`: WhatsApp cannot edit a message, so the router sends the
        answer whole - and `open_answer`'s `None` keeps a streaming bot off the
        edit path too. Never fatal; the indicator is decoration.
        """
        if not msg.reply_to_message_id:
            return None
        creds: WhatsAppCredentials | None = None
        try:
            creds = WhatsAppCredentials.decode(bot_token)
            await self._graph.mark_read(creds, message_id=msg.reply_to_message_id, typing=True)
        except Exception as failure:
            _typing_failed(creds, failure)
            return None
        key = (creds.bot_id, msg.platform_chat_id)
        self._stop_typing(key)
        self._typing[key] = spawn(
            self._keep_typing(key, creds, msg.reply_to_message_id),
            name=f"whatsapp_typing:{creds.bot_id}",
        )
        return None

    async def _keep_typing(
        self, key: tuple[str, str], creds: WhatsAppCredentials, message_id: str
    ) -> None:
        try:
            waited = 0.0
            while waited + TYPING_REFRESH_SECONDS <= TYPING_MAX_SECONDS:
                await _sleep(TYPING_REFRESH_SECONDS)
                waited += TYPING_REFRESH_SECONDS
                await self._graph.mark_read(creds, message_id=message_id, typing=True)
        except Exception as failure:
            _typing_failed(creds, failure)
        # Not in a `finally`: a cancelled refresher was already taken out of the
        # table by whoever cancelled it, and a newer reply may own the key by now.
        self._typing.pop(key, None)

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """WhatsApp has nothing to poll: Meta posts every message to the bot's endpoint."""

    async def stop_polling(self, bot_id: str) -> None:
        """Nothing was started."""

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """The callback is set in Meta's app dashboard, not through an API.

        Logged so an operator has the address to paste.
        """
        logger.info("WhatsApp: set the app's webhook callback URL to %s", url)
        return False

    async def delete_webhook(self, bot_token: str) -> bool:
        return False

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """Meta's `X-Hub-Signature-256` over the body, under the app secret."""
        if body is None:
            return False
        return verify_signature(body.encode(), headers.get("x-hub-signature-256"), secret)

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """Never: a webhook carries a batch, which the route reads with `parse_webhook`."""
        return None


def whatsapp_adapter() -> WhatsAppAdapter:
    """The registered adapter, or one registered now.

    The API registers it at startup; the job worker (`python -m app.worker`) never
    does, so code that will send from the worker - a trigger's result, a
    proactive message - asks for it here, as `teams_adapter()` is asked. Nothing
    calls it yet.
    """
    from app.services.channels import get_adapter, register_adapter

    try:
        adapter = get_adapter(WhatsAppAdapter.platform)
    except KeyError:
        adapter = WhatsAppAdapter()
        register_adapter(adapter)
    if not isinstance(adapter, WhatsAppAdapter):  # pragma: no cover - registered by platform
        raise TypeError("The adapter registered for WhatsApp is not the WhatsApp adapter")
    return adapter
