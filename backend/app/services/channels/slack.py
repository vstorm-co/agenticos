"""Slack channel adapter using slack-sdk.

Supports:
- Events API (webhook mode) - production
- Socket Mode (polling equivalent) - development
- Thread-aware sessions: messages in a Slack thread get their own
  ChannelSession / Conversation (thread_ts folded into platform_chat_id)
- @mention detection in channels
"""

import asyncio
import contextlib
import hashlib
import hmac
import logging
import time
from typing import Any

from app.db.session import get_db_context
from app.services.channels.base import (
    ChannelAdapter,
    IncomingAttachment,
    IncomingMessage,
    OutgoingMessage,
)
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.router import ChannelMessageRouter

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """Concrete Slack adapter using slack-sdk."""

    platform: str = "slack"

    def __init__(self) -> None:
        self._socket_tasks: dict[str, asyncio.Task[None]] = {}
        # Each bot is its own Slack app, so Socket Mode connects with that
        # bot's xapp- token. Registered before polling starts, the same way
        # Mattermost's per-bot server address is.
        self._app_tokens: dict[str, str] = {}

    def remember_app_token(self, bot_id: str, app_token: str) -> None:
        """Register the app-level token Socket Mode will connect with."""
        self._app_tokens[bot_id] = app_token

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Post the message that will become the answer, and return its `ts`.

        A Slack message is addressed by the timestamp it was posted at, so that
        is the handle - and in a thread it is *also* what a reply is keyed to,
        which is why the channel and the thread are split apart here the same way
        `send_message` splits them.
        """
        from slack_sdk.web.async_client import AsyncWebClient

        channel, _, thread_ts = msg.platform_chat_id.partition(":")
        kwargs: dict[str, Any] = {"channel": channel, "text": msg.text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        response = await AsyncWebClient(token=bot_token).chat_postMessage(**kwargs)
        posted = response.get("ts")
        return str(posted) if posted else None

    async def update_reply(self, bot_token: str, msg: OutgoingMessage, handle: str) -> None:
        """Rewrite a message already in the channel."""
        from slack_sdk.web.async_client import AsyncWebClient

        channel, _, _thread_ts = msg.platform_chat_id.partition(":")
        await AsyncWebClient(token=bot_token).chat_update(channel=channel, ts=handle, text=msg.text)

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Send a reply back to Slack via the Web API."""
        from slack_sdk.web.async_client import AsyncWebClient

        client = AsyncWebClient(token=bot_token)

        # If platform_chat_id contains ":" it includes a thread_ts
        channel, _, thread_ts = msg.platform_chat_id.partition(":")

        kwargs: dict[str, Any] = {
            "channel": channel,
            "text": msg.text,
        }
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        if "thread_ts" not in kwargs and msg.reply_to_message_id:
            kwargs["thread_ts"] = msg.reply_to_message_id
        if msg.image_png is not None:
            await client.files_upload_v2(
                channel=channel,
                file=msg.image_png,
                filename=msg.image_filename,
                initial_comment=msg.text,
                thread_ts=kwargs.get("thread_ts"),
            )
            return

        if msg.attachments:
            # `files_upload_v2` with several files posts them as one message with
            # the text as its comment, which is what a reply about a file should
            # look like - the alternative is an answer and then, separately, some
            # files.
            await client.files_upload_v2(
                channel=channel,
                initial_comment=msg.text,
                thread_ts=kwargs.get("thread_ts"),
                file_uploads=[
                    {
                        "file": attachment.content,
                        "filename": attachment.filename,
                    }
                    for attachment in msg.attachments
                ],
            )
            return

        await client.chat_postMessage(**kwargs)

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """Start Slack Socket Mode (equivalent to polling for dev)."""
        if bot_id in self._socket_tasks and not self._socket_tasks[bot_id].done():
            logger.info("Socket Mode already running for bot %s", bot_id)
            return

        task = asyncio.create_task(
            self._socket_supervisor(bot_id, bot_token),
            name=f"slack_socket_{bot_id}",
        )
        self._socket_tasks[bot_id] = task
        logger.info("Started Slack Socket Mode for bot %s", bot_id)

    async def stop_polling(self, bot_id: str) -> None:
        """Stop Socket Mode for this bot."""
        task = self._socket_tasks.pop(bot_id, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("Stopped Slack Socket Mode for bot %s", bot_id)

    async def _socket_supervisor(self, bot_id: str, bot_token: str) -> None:
        """Supervised loop: restart Socket Mode on crash.

        The sleep is outside the `except` on purpose. `_run_socket_mode` has
        branches that return without ever awaiting, and awaiting a coroutine
        that never suspends does not yield to the event loop - so this looped at
        100% CPU and no other task on the process was scheduled again. The API
        stayed up and answered nothing, health check included, on one WARNING
        line.
        """
        while True:
            try:
                await self._run_socket_mode(bot_id, bot_token)
            except asyncio.CancelledError:
                break
            except ChannelNotConfigured:
                # Not a crash and not something a retry fixes: an operator has
                # to add the token. Retrying would be the spin all over again.
                logger.warning("Slack Socket Mode not started for bot %s", bot_id)
                return
            except Exception:
                logger.exception("Slack Socket Mode crashed for bot %s, restarting in 5s", bot_id)
            await asyncio.sleep(5)

    async def _run_socket_mode(self, bot_id: str, bot_token: str) -> None:
        """Run one Socket Mode session."""
        try:
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.socket_mode.request import SocketModeRequest
            from slack_sdk.socket_mode.response import SocketModeResponse
        except ImportError as exc:
            raise ChannelNotConfigured(
                message=(
                    "Slack Socket Mode requires 'slack-sdk[socket-mode]'. "
                    "Install with: pip install 'slack-sdk[socket-mode]'"
                ),
                details={"bot_id": bot_id},
            ) from exc

        app_token = self._app_tokens.get(bot_id)
        if not app_token:
            raise ChannelNotConfigured(
                message=(
                    "Slack bot has no app-level token - Socket Mode not started. "
                    "Add the xapp- token in the bot's settings."
                ),
                details={"bot_id": bot_id},
            )

        client = SocketModeClient(
            app_token=app_token,
            web_client=__import__(
                "slack_sdk.web.async_client", fromlist=["AsyncWebClient"]
            ).AsyncWebClient(token=bot_token),
        )

        async def handler(client_: Any, req: SocketModeRequest) -> None:
            await client_.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            if req.type == "events_api":
                event = req.payload.get("event", {})
                await self._handle_event(event, bot_id)

        client.socket_mode_request_listeners.append(handler)  # type: ignore[arg-type]
        await client.connect()
        while True:
            await asyncio.sleep(1)

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """Slack doesn't have a register webhook API - configuration is done
        in the Slack app dashboard. This is a no-op that returns True."""
        logger.info("Slack: webhook URL should be configured in Slack app settings: %s", url)
        return True

    async def delete_webhook(self, bot_token: str) -> bool:
        """Slack doesn't have a delete webhook API. No-op."""
        return True

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """Verify Slack request signature (HMAC-SHA256).

        Slack signs requests with: v0=HMAC-SHA256(signing_secret, "v0:{timestamp}:{body}")
        The raw request body must be passed via the `body` parameter.
        """
        timestamp = headers.get("x-slack-request-timestamp", "")
        signature = headers.get("x-slack-signature", "")
        raw_body = body or ""

        # Reject missing timestamp (required for replay protection)
        if not timestamp or not signature:
            return False

        # Reject requests older than 5 minutes (replay protection)
        try:
            ts = int(timestamp)
        except ValueError:
            return False
        if abs(time.time() - ts) > 300:
            return False

        base_string = f"v0:{timestamp}:{raw_body}"
        computed = (
            "v0=" + hmac.new(secret.encode(), base_string.encode(), hashlib.sha256).hexdigest()
        )

        return hmac.compare_digest(computed, signature)

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """Parse a Slack event payload into IncomingMessage.

        Handles `message` events (direct messages and channel messages).
        Ignores bot messages, message_changed, and other subtypes.
        Thread replies get thread_ts folded into platform_chat_id.
        """
        event: dict[str, Any] = raw_payload.get("event", raw_payload)

        event_type: str = event.get("type", "")
        if event_type != "message" and event_type != "app_mention":
            return None

        # Ignore bot messages and edits
        if event.get("bot_id") or event.get("subtype"):
            return None

        attachments = self._attachments(event)
        text: str = event.get("text") or ""
        if not text and not attachments:
            return None

        user_id: str = event.get("user", "")
        channel: str = event.get("channel", "")
        channel_type: str = event.get("channel_type", "channel")
        thread_ts: str | None = event.get("thread_ts")
        message_ts: str | None = event.get("ts")

        chat_type = "private" if channel_type in ("im", "mpim") else "group"

        # For threads: fold thread_ts into platform_chat_id so each thread
        # gets its own ChannelSession and Conversation
        platform_chat_id = f"{channel}:{thread_ts}" if thread_ts else channel

        return IncomingMessage(
            platform="slack",
            bot_id=bot_id,
            platform_user_id=user_id,
            platform_chat_id=platform_chat_id,
            chat_type=chat_type,
            text=text,
            raw=raw_payload,
            platform_username=None,  # resolved later if needed
            platform_display_name=None,
            message_id=message_ts,
            attachments=attachments,
        )

    @staticmethod
    def _attachments(event: dict[str, Any]) -> list[IncomingAttachment]:
        """The files on a Slack message, as handles.

        `url_private_download` is carried as the handle rather than the file id: it
        is what the download actually uses, and resolving an id through
        `files.info` at parse time would put an HTTP call in a synchronous parser.
        Slack includes it on the event, so there is nothing to look up.

        A file still being processed has no download URL yet and is skipped. It
        arrives again on `file_shared` when Slack has finished with it; treating a
        missing URL as a failure would report an error for something that is
        merely not ready.
        """
        found: list[IncomingAttachment] = []
        for file in event.get("files") or []:
            if not isinstance(file, dict):
                continue
            url = file.get("url_private_download") or file.get("url_private")
            if not url:
                continue
            found.append(
                IncomingAttachment(
                    filename=file.get("name") or "file",
                    mime_type=file.get("mimetype") or "application/octet-stream",
                    size=int(file.get("size") or 0),
                    handle=str(url),
                )
            )
        return found

    async def download_attachment(self, bot_token: str, attachment: IncomingAttachment) -> bytes:
        """Fetch a Slack file with the bot token.

        Slack's file URLs are private: an unauthenticated GET answers 200 with an
        HTML sign-in page rather than a 401, so a client that did not send the
        token would store that page as the user's spreadsheet. Hence the explicit
        content-type check - the failure mode here is silent corruption, not an
        error.
        """
        import httpx

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(
                attachment.handle, headers={"Authorization": f"Bearer {bot_token}"}
            )
        response.raise_for_status()
        if response.headers.get("content-type", "").startswith("text/html"):
            raise ValueError(
                f"Slack answered with a sign-in page for {attachment.filename}; "
                "the bot token cannot read that file."
            )
        return response.content

    async def _handle_event(self, event: dict[str, Any], bot_id: str) -> None:
        """Handle a Slack event from Socket Mode or webhook."""
        incoming = self.parse_incoming({"event": event}, bot_id)
        if incoming is None:
            return

        router = ChannelMessageRouter()

        async with get_db_context() as db:
            await router.route(incoming, db)
