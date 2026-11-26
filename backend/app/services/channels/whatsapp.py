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
from collections.abc import Awaitable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.background import spawn
from app.core.config import settings
from app.services.channels import connection_state
from app.services.channels.base import (
    ChannelAdapter,
    IncomingAttachment,
    IncomingMessage,
    IncomingPress,
    OutgoingMessage,
    PromptMessage,
)
from app.services.channels.whatsapp_customers import WindowStore
from app.services.channels.whatsapp_format import split_message, to_whatsapp, utf16_units
from app.services.channels.whatsapp_graph import (
    CLOSED_WINDOW_CODE,
    TOKEN_REFUSED,
    WhatsAppCredentials,
    WhatsAppGraph,
    WhatsAppGraphError,
    WhatsAppTokenRefused,
    WhatsAppWindowClosed,
    WhatsAppWindowUnavailable,
    is_template_refusal,
)
from app.services.channels.whatsapp_interactive import plan_interactive
from app.services.channels.whatsapp_payload import verify_signature
from app.services.channels.whatsapp_window import fits, flatten, preview
from app.services.transcription import MAX_BYTES as TRANSCRIPTION_MAX_BYTES

logger = logging.getLogger(__name__)

TYPING_REFRESH_SECONDS: float = 20
"""Meta clears the indicator after 25 seconds; this re-sends it before that."""

TYPING_MAX_SECONDS: float = 300
"""A turn that has not answered by now is not going to; stop claiming it is typing."""

_sleep = asyncio.sleep
"""The refresher's clock, a name of its own so a test can advance it by hand."""


def _now() -> datetime:
    """The window's clock, a name of its own so a test can freeze it."""
    return datetime.now(UTC)


FILE_NOT_SENT = "(A file that came with this answer could not be sent.)"
"""Said instead of dropping a file silently when Meta refused its upload."""

CAPTION_MAX = 1024
"""Meta's limit on a caption, counted in UTF-16 code units like a text message's."""

IMAGE_MAX_BYTES = 5 * 1024 * 1024
"""Meta shows a JPEG or PNG up to this size as a picture; anything else is a document."""

_IMAGE_TYPES = frozenset({"image/jpeg", "image/png"})


@dataclass(frozen=True)
class _Upload:
    media_id: str
    kind: Literal["image", "document"]
    filename: str


def _code_of(failure: WhatsAppGraphError | WhatsAppTokenRefused) -> int | None:
    return (failure.details or {}).get("code")


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
    # Decided in the design, not verified on a device: offering the question again is
    # right whether or not WhatsApp keeps a tapped message's buttons live.
    buttons_outlive_a_press = False

    def __init__(
        self, graph: WhatsAppGraph | None = None, window: WindowStore | None = None
    ) -> None:
        self._graph = graph or WhatsAppGraph()
        self._window = window or WindowStore()
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

        Inside the customer's 24-hour window (or when nothing is recorded for them)
        this is `_send_now`. Outside it the answer goes in the late-answer template
        when it fits and otherwise as a preview, with its run held until the
        customer writes again; see `_send_late`. Meta's 131047 is the authority:
        a send it refuses as outside the window takes the late path too.

        Raises:
            WhatsAppTokenRefused: Meta refused the access token; the bot is marked
                down in the console list until a send succeeds.
            WhatsAppWindowClosed: Outside the window and no template could carry a
                message that belongs to no run.
            WhatsAppWindowUnavailable: Outside the window, and the record could not be
                read or written, so the answer could not be held.
            WhatsAppGraphError: Any other refusal, or every file was refused and
                there was no text to send instead: the caller (`send_channel_file`)
                must not report a delivery that did not happen.
        """
        creds = WhatsAppCredentials.decode(bot_token)
        self._stop_typing((creds.bot_id, msg.platform_chat_id))
        if not (to_whatsapp(msg.text).strip() or msg.image_png or msg.attachments):
            await self._send_now(creds, msg)
            return
        if await self._window_state(creds, msg.platform_chat_id) is False:
            await self._send_late(creds, msg)
            return
        attempted = _now().replace(microsecond=0)
        try:
            await self._send_now(creds, msg)
        except WhatsAppGraphError as failure:
            if _code_of(failure) != CLOSED_WINDOW_CODE:
                raise
            await self._close_window(creds, msg.platform_chat_id, at=attempted)
            await self._send_late(creds, msg, refused_by_meta=True)

    async def _window_state(self, creds: WhatsAppCredentials, chat_id: str) -> bool | None:
        """Whether the window is open; `None` when nothing is recorded or it cannot be read.

        Meta is the authority, so a record that cannot be read never blocks a send.
        """
        try:
            return await self._window.window(creds.bot_id, chat_id, now=_now())
        except Exception as failure:
            logger.warning(
                "whatsapp_window_unread",
                extra={"bot_id": creds.bot_id, "error": type(failure).__name__},
            )
            return None

    async def _close_window(
        self, creds: WhatsAppCredentials, chat_id: str, *, at: datetime
    ) -> None:
        """Record that Meta said the window is closed; a record that cannot be written is only logged.

        `at` is the send attempt's time, floored to the second: Meta stamps a
        customer's message in whole seconds, and a message in the same second as
        a closure counts as the later event (`window_open`), so it reopens the window.
        """
        try:
            await self._window.close(creds.bot_id, chat_id, at=at)
        except Exception as failure:
            logger.warning(
                "whatsapp_window_unwritten",
                extra={"bot_id": creds.bot_id, "error": type(failure).__name__},
            )

    async def _send_now(self, creds: WhatsAppCredentials, msg: OutgoingMessage) -> None:
        """Send as a free-form message: the chart and files, then the text.

        Every file is uploaded before anything is sent. A file Meta refuses
        (`WhatsAppGraphError`) is dropped and `FILE_NOT_SENT` is added to the
        answer once. A short answer (at most 1024 UTF-16 units) is the first file's
        caption and no text message is sent; a longer one goes first as text and
        the files follow without captions. When the only text is that note, it
        follows the files as a text message. The reply context goes on the first
        message actually sent.
        """
        text = to_whatsapp(msg.text).strip()
        reply_to = msg.reply_to_message_id
        # A notice carries no callback data: a later `failed` status on it must not
        # hold the run as an answer.
        callback = None if msg.notice else msg.run_id
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
                reply_to = await self._send_text(
                    creds, msg.platform_chat_id, text, reply_to, callback
                )
            for upload in uploads:
                await self._graph.send_media(
                    creds,
                    recipient=msg.platform_chat_id,
                    kind=upload.kind,
                    media_id=upload.media_id,
                    caption=caption,
                    filename=upload.filename,
                    reply_to=reply_to,
                    callback=callback,
                )
                caption = reply_to = None
            if note_only:
                await self._send_text(creds, msg.platform_chat_id, text, reply_to, callback)
        except WhatsAppTokenRefused:
            await connection_state.record_down(creds.bot_id, TOKEN_REFUSED)
            raise
        await self._record_sent(creds)

    async def _guarded[T](
        self, creds: WhatsAppCredentials, run_id: str | None, call: Awaitable[T]
    ) -> T:
        """Await a store call; a failure is logged by type and becomes `WhatsAppWindowUnavailable`.

        The store's own exception carries SQL parameters, which include the customer's
        id, so it is dropped here instead of reaching a caller's `logger.exception`.
        """
        try:
            return await call
        except Exception as failure:
            logger.warning(
                "whatsapp_window_store_failed",
                extra={
                    "bot_id": creds.bot_id,
                    "run_id": run_id,
                    "error": type(failure).__name__,
                },
            )
            raise WhatsAppWindowUnavailable() from None

    async def _hold(
        self,
        creds: WhatsAppCredentials,
        chat_id: str,
        *,
        run_id: str,
        answer: bool,
        files: bool,
        refused_by_meta: bool,
        notice: str | None = None,
    ) -> bool:
        """Hold the run; False when it was not held because the record says the window is open.

        A `notice` (the key of a fixed sentence) is held as a notice: it owes no answer.

        A send Meta has just refused as outside the window is held without asking the
        record: Meta is the authority, and a stale record must not drop the run.
        """
        if refused_by_meta:
            await self._guarded(
                creds,
                run_id,
                self._window.hold(
                    creds.bot_id, chat_id, run_id=run_id, answer=answer, files=files, notice=notice
                ),
            )
            return True
        opened = await self._guarded(
            creds,
            run_id,
            self._window.hold_unless_open(
                creds.bot_id,
                chat_id,
                run_id=run_id,
                answer=answer,
                files=files,
                now=_now(),
                notice=notice,
            ),
        )
        return not opened

    async def _hold_after_token_refusal(
        self, creds: WhatsAppCredentials, msg: OutgoingMessage, has_files: bool
    ) -> None:
        """Hold the run and say why after the token was refused; a store failure never hides the token error.

        A notice is held as a notice, and the run's reason (about its answers) is left alone.
        """
        run_id = msg.run_id
        if run_id is None:
            return
        with suppress(WhatsAppWindowUnavailable):  # already logged; the token error is what counts
            await self._hold(
                creds,
                msg.platform_chat_id,
                run_id=run_id,
                answer=msg.notice is None,
                files=has_files,
                refused_by_meta=True,
                notice=msg.notice,
            )
            if msg.notice is not None:
                return
            await self._guarded(
                creds,
                run_id,
                self._window.record_undelivered(creds.bot_id, run_id, "window_template_failed"),
            )

    async def _send_late(
        self, creds: WhatsAppCredentials, msg: OutgoingMessage, *, refused_by_meta: bool = False
    ) -> None:
        """Send a message the window no longer allows: in the template, as a held preview, or not at all.

        - The answer fits the bot's template: it goes in it whole.
        - Otherwise a message with no run is refused (`WhatsAppWindowClosed`), and
          one with a run is held and previewed by `send_held_preview`.
        - A template Meta refuses for any reason other than the token is tried once
          more as a preview when there is a run.
        - A notice (`msg.notice`) is never previewed: in the template when it fits,
          otherwise held as a notice and sent when the customer writes. It is sent
          with no callback data and never touches the run's reason, which is about
          its answers.
        - A store that fails holds nothing it cannot hold: `WhatsAppWindowUnavailable`.
          An unreadable template holds the run with a reason instead.
        """
        text = to_whatsapp(msg.text).strip()
        has_files = bool(msg.image_png or msg.attachments)
        run_id = msg.run_id
        notice = msg.notice
        try:
            template = await self._guarded(creds, run_id, self._window.late_template(creds.bot_id))
        except WhatsAppWindowUnavailable:
            if run_id is None:
                raise WhatsAppWindowClosed() from None
            await self._hold(
                creds,
                msg.platform_chat_id,
                run_id=run_id,
                answer=notice is None,
                files=has_files,
                refused_by_meta=True,
                notice=notice,
            )
            if notice is None:
                await self._guarded(
                    creds,
                    run_id,
                    self._window.record_undelivered(creds.bot_id, run_id, "window_template_failed"),
                )
            return
        if template is not None and fits(
            text, fixed_length=template.fixed_length, has_files=has_files
        ):
            try:
                await self._graph.send_template(
                    creds,
                    recipient=msg.platform_chat_id,
                    template=template,
                    text=flatten(text),
                    callback=None if notice else run_id,
                )
            except WhatsAppTokenRefused:
                await self._hold_after_token_refusal(creds, msg, has_files)
                await connection_state.record_down(creds.bot_id, TOKEN_REFUSED)
                raise
            except WhatsAppGraphError as failure:
                logger.warning(
                    "whatsapp_late_template_refused",
                    extra={
                        "bot_id": creds.bot_id,
                        "run_id": run_id,
                        "code": _code_of(failure),
                        "template_refusal": is_template_refusal(_code_of(failure)),
                    },
                )
                if run_id is None:
                    raise WhatsAppWindowClosed() from None
            else:
                if run_id is not None and notice is None:
                    # Delivered: a reason that stays is logged, not raised over a sent answer.
                    with suppress(WhatsAppWindowUnavailable):
                        await self._guarded(
                            creds,
                            run_id,
                            self._window.record_undelivered(creds.bot_id, run_id, None),
                        )
                await self._record_sent(creds)
                return
        if run_id is None:
            raise WhatsAppWindowClosed()
        held = await self._hold(
            creds,
            msg.platform_chat_id,
            run_id=run_id,
            answer=notice is None,
            files=has_files,
            refused_by_meta=refused_by_meta,
            notice=notice,
        )
        if not held:
            await self._send_now(creds, msg)
            return
        if notice is not None:
            return
        await self.send_held_preview(creds.encode(), msg)

    async def send_held_preview(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Say that an answer is waiting, for a run that is already held; never sends the answer itself.

        With no template nothing is sent and the run records why. A preview Meta
        refuses records `window_template_failed`; the run stays held either way, and
        its answer goes out when the customer writes again.

        Raises:
            WhatsAppTokenRefused: Meta refused the access token; the run records why
                and the bot is marked down.
            WhatsAppWindowClosed: The message belongs to no run, so there is nothing to hold.
            WhatsAppWindowUnavailable: The record could not be read or written; the
                run stays held.
        """
        run_id = msg.run_id
        if run_id is None:
            raise WhatsAppWindowClosed()
        creds = WhatsAppCredentials.decode(bot_token)
        template = await self._guarded(creds, run_id, self._window.late_template(creds.bot_id))
        if template is None:
            await self._guarded(
                creds,
                run_id,
                self._window.record_undelivered(creds.bot_id, run_id, "window_no_template"),
            )
            return

        async def record_failed() -> None:
            await self._guarded(
                creds,
                run_id,
                self._window.record_undelivered(creds.bot_id, run_id, "window_template_failed"),
            )

        try:
            await self._graph.send_template(
                creds,
                recipient=msg.platform_chat_id,
                template=template,
                text=preview(to_whatsapp(msg.text).strip()),
                callback=run_id,
            )
        except WhatsAppTokenRefused:
            # A store failure is already logged; the token refusal is what the caller sees.
            with suppress(WhatsAppWindowUnavailable):
                await record_failed()
            await connection_state.record_down(creds.bot_id, TOKEN_REFUSED)
            raise
        except WhatsAppGraphError as failure:
            logger.warning(
                "whatsapp_late_preview_refused",
                extra={"bot_id": creds.bot_id, "run_id": run_id, "code": _code_of(failure)},
            )
            await record_failed()
            return
        await self._record_sent(creds)

    @staticmethod
    async def _record_sent(creds: WhatsAppCredentials) -> None:
        """Clear a "down" after a send went through.

        Read from the shared entry, not remembered here: the worker whose send
        succeeds is rarely the one that saw the refusal.
        """
        recorded = await connection_state.read(creds.bot_id)
        if recorded is not None and recorded.state == "down":
            await connection_state.record_up(creds.bot_id)

    async def _send_text(
        self,
        creds: WhatsAppCredentials,
        chat_id: str,
        text: str,
        reply_to: str | None,
        callback: str | None,
    ) -> str | None:
        """Send `text` in as many messages as its limit needs; the reply context goes first.

        Returns the reply context still unused: none when a message went out.
        """
        for chunk in split_message(text):
            await self._graph.send_text(
                creds, recipient=chat_id, body=chunk, reply_to=reply_to, callback=callback
            )
            reply_to = None
        return reply_to

    async def send_prompt(self, bot_token: str, prompt: PromptMessage) -> None:
        """Send an approval or a question as reply buttons or a list.

        A prompt that fits neither (no choices, or more than a list holds) goes as the
        base class's text list. Text too long for the interactive body goes first, as
        ordinary messages. Outside the 24-hour window nothing can be sent: the prompt's
        run is held, and it is offered again when the customer writes.

        Raises:
            WhatsAppTokenRefused: Meta refused the access token; the bot is marked
                down in the console list until a send succeeds.
            WhatsAppWindowClosed: The window is closed; the run waiting on the
                prompt is held (a prompt with no run is dropped).
            WhatsAppWindowUnavailable: The window is closed and the record could not be
                read or written, so the run could not be held.
            WhatsAppGraphError: Any other refusal.
        """
        creds = WhatsAppCredentials.decode(bot_token)
        if await self._window_state(creds, prompt.platform_chat_id) is False:
            await self._hold_prompt(creds, prompt, refused_by_meta=False)
        plan = plan_interactive(to_whatsapp(prompt.text).strip(), prompt.choices)
        self._stop_typing((creds.bot_id, prompt.platform_chat_id))
        attempted = _now().replace(microsecond=0)
        try:
            if plan is None:
                # The base class's text list, sent here: a refusal as outside the window
                # must hold the run as a prompt, not as an answer (`send_message`).
                listed = "\n".join(f"- {choice.label}" for choice in prompt.choices)
                await self._send_now(
                    creds,
                    OutgoingMessage(
                        platform_chat_id=prompt.platform_chat_id,
                        text=f"{prompt.text}\n{listed}",
                        api_base_url=prompt.api_base_url,
                        run_id=prompt.run_id,
                    ),
                )
                return
            if plan.preamble:
                for chunk in split_message(plan.preamble):
                    await self._graph.send_text(
                        creds,
                        recipient=prompt.platform_chat_id,
                        body=chunk,
                        callback=prompt.run_id,
                    )
            await self._graph.send_interactive(
                creds,
                recipient=prompt.platform_chat_id,
                interactive=plan.interactive,
                callback=prompt.run_id,
            )
        except WhatsAppTokenRefused:
            if plan is not None:  # `_send_now` has recorded it for the text list
                await connection_state.record_down(creds.bot_id, TOKEN_REFUSED)
            raise
        except WhatsAppGraphError as failure:
            if _code_of(failure) != CLOSED_WINDOW_CODE:
                raise
            await self._close_window(creds, prompt.platform_chat_id, at=attempted)
            await self._hold_prompt(creds, prompt, refused_by_meta=True)  # always raises
        await self._record_sent(creds)

    async def _hold_prompt(
        self, creds: WhatsAppCredentials, prompt: PromptMessage, *, refused_by_meta: bool
    ) -> None:
        """Hold the run waiting on a prompt the window refuses, and raise `WhatsAppWindowClosed`.

        Returns only when the record says the window is open and Meta has not said
        otherwise, so the caller sends the prompt as usual. The held run offers the
        prompt again after the customer's next message.
        """
        if prompt.run_id is None:
            raise WhatsAppWindowClosed()
        held = await self._hold(
            creds,
            prompt.platform_chat_id,
            run_id=prompt.run_id,
            answer=False,
            files=False,
            refused_by_meta=refused_by_meta,
        )
        if held:
            raise WhatsAppWindowClosed()

    async def acknowledge(self, bot_token: str, press: IncomingPress) -> None:
        """Mark the tap read and show "typing" until the run's answer is sent. Never fatal."""
        if not press.ack_id:
            return
        creds: WhatsAppCredentials | None = None
        try:
            creds = WhatsAppCredentials.decode(bot_token)
            await self._graph.mark_read(creds, message_id=press.ack_id, typing=True)
        except Exception as failure:
            _typing_failed(creds, failure)
            return
        self._start_typing(creds, press.platform_chat_id, press.ack_id)

    async def settle_prompt(self, bot_token: str, press: IncomingPress, text: str) -> None:
        """Say what was chosen, quoting the prompt: a sent message cannot be edited.

        Never fatal, as `acknowledge` is: here the confirmation is a send, and it runs
        after the tap has already continued the run. It only decorates the answer that
        follows, so a failure is logged by bot and exception type and the answer, the
        next prompt and the next step go on.
        """
        creds: WhatsAppCredentials | None = None
        try:
            creds = WhatsAppCredentials.decode(bot_token)
            await self.send_message(
                bot_token,
                OutgoingMessage(
                    platform_chat_id=press.platform_chat_id,
                    text=text,
                    reply_to_message_id=press.message_id,
                ),
            )
        except Exception as failure:
            logger.warning(
                "whatsapp_settle_failed",
                extra={
                    "bot_id": creds.bot_id if creds else None,
                    "error": type(failure).__name__,
                },
            )

    def press_matches_chat(self, press: IncomingPress, platform_chat_id: str) -> bool:
        """A chat is one customer, so a tap from anyone else is not an answer to this prompt."""
        return press.platform_chat_id == platform_chat_id

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

    async def download_attachment(
        self, bot_token: str, attachment: IncomingAttachment, *, max_bytes: int | None = None
    ) -> bytes:
        """Fetch a customer's file; the lookup is repeated because Meta's URL lives 5 minutes."""
        creds = WhatsAppCredentials.decode(bot_token)
        info = await self._graph.media_info(creds, media_id=attachment.handle)
        limit = (
            TRANSCRIPTION_MAX_BYTES
            if attachment.mime_type.startswith("audio/")
            else settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
        )
        if max_bytes is not None:
            limit = min(limit, max_bytes)
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
        self._start_typing(creds, msg.platform_chat_id, msg.reply_to_message_id)
        return None

    def _start_typing(self, creds: WhatsAppCredentials, chat_id: str, message_id: str) -> None:
        """Keep the indicator up for this chat, replacing a refresher already running."""
        key = (creds.bot_id, chat_id)
        self._stop_typing(key)
        self._typing[key] = spawn(
            self._keep_typing(key, creds, message_id),
            name=f"whatsapp_typing:{creds.bot_id}",
        )

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
    does, so code that sends from the worker - an expiry or stranded-run notice -
    asks for it here, as `teams_adapter()` is asked.
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
