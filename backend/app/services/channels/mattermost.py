"""Mattermost channel adapter.

Mattermost is self-hosted, which is the one thing that makes it different from
the other two adapters: there is no api.mattermost.com to talk to, so every bot
carries the URL of its own server (`ChannelBot.api_base_url`). A bot without one
cannot send anything, and that is reported when the bot is saved rather than the
first time somebody messages it.

Two ways in, both supported, because Mattermost deployments differ:

*Outgoing webhooks* - Mattermost POSTs to us when a trigger word matches or a
message lands in a watched channel. Configured in Mattermost's own integrations
page, so `register_webhook` has nothing to call; it logs the URL to paste. The
payload carries a shared `token`, which is what `verify_webhook_signature`
compares - Mattermost does not sign bodies the way Slack does, so this is a
bearer check and the token must be treated as a credential.

*The WebSocket event stream* - a bot token authenticates, and every `posted`
event arrives. This is the equivalent of Slack's Socket Mode: nothing to expose
publicly, which is what a private deployment behind a VPN needs. It is what
`start_polling` runs.

Both paths normalise into the same `IncomingMessage`, so the router, the access
policy and the mention handling are shared with Slack and Telegram.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from typing import Any
from urllib.parse import parse_qs

import httpx

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

# Mattermost closes an idle socket; the client is expected to keep it warm.
_PING_SECONDS = 30.0
_HTTP_TIMEOUT = 20.0


def decode_webhook_body(raw: str) -> dict[str, Any]:
    """One outgoing-webhook body, whichever encoding the integration was given.

    Mattermost sends JSON or `application/x-www-form-urlencoded` depending on
    how the integration was set up, and the two halves of receiving one - the
    token check below and the message itself - have to agree on which it was.
    They did not. The token was found by trying JSON and falling back to a form
    parse; the message was decoded from the declared Content-Type instead, so a
    body whose header disagreed with its bytes authenticated and then parsed to
    nothing. The webhook answered 200 and the message was never delivered.

    Which is why the header is not consulted at all: what a body *is* settles
    it, and a form body is never valid JSON. Anything neither reads as an empty
    payload, which downstream takes as "no message here" - and no token can be
    found in it, so this cannot widen what authenticates.
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {key: values[0] for key, values in parse_qs(raw).items()}
    return parsed if isinstance(parsed, dict) else {}


class MattermostAdapter(ChannelAdapter):
    """Mattermost, over its REST API and its WebSocket event stream."""

    platform: str = "mattermost"

    def __init__(self) -> None:
        self._socket_tasks: dict[str, asyncio.Task[None]] = {}
        # Where each bot's server lives. Set by the service when a bot starts,
        # because the adapter is a singleton and the URL is per bot.
        self._base_urls: dict[str, str] = {}

    def remember_server(self, bot_id: str, api_base_url: str) -> None:
        """Record which Mattermost server a bot belongs to."""
        self._base_urls[bot_id] = api_base_url.rstrip("/")

    # --- sending -----------------------------------------------------------

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Post a reply.

        `platform_chat_id` is `channel_id` or `channel_id:root_id`; the second
        form is a thread, folded the same way Slack's is so one conversation per
        thread falls out of the router without it knowing about threads.
        """
        if not msg.api_base_url:
            raise ValueError("Mattermost bot has no server URL. Set it on the bot before sending.")
        # Trailing slash stripped here rather than trusted from the row: an
        # operator types `https://mattermost.acme.com/` roughly half the time,
        # and `{base}/api/v4/posts` then has two slashes in it. Mattermost
        # answers a 301 to the single-slash form, httpx does not follow a
        # redirect on a POST by default, and the reply is lost with a
        # `HTTPStatusError` in the log rather than an answer in the thread.
        # `remember_server` has always stripped it, so the socket path was fine
        # and only replies failed - which is the confusing half of the bug.
        base_url = msg.api_base_url.rstrip("/")

        channel_id, _, root_id = msg.platform_chat_id.partition(":")
        headers = {"Authorization": f"Bearer {bot_token}"}

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            # One upload for the chart and the attachments together: Mattermost
            # attaches files to a post by id, so both halves are the same call and
            # a post referencing them follows.
            uploads: list[tuple[str, tuple[str, bytes, str]]] = []
            if msg.image_png is not None:
                uploads.append(("files", (msg.image_filename, msg.image_png, "image/png")))
            uploads.extend(
                ("files", (attachment.filename, attachment.content, attachment.mime_type))
                for attachment in msg.attachments
            )

            file_ids: list[str] = []
            if uploads:
                upload = await client.post(
                    f"{base_url}/api/v4/files",
                    headers=headers,
                    data={"channel_id": channel_id},
                    files=uploads,
                )
                upload.raise_for_status()
                file_ids = [item["id"] for item in upload.json().get("file_infos", [])]

            body: dict[str, Any] = {"channel_id": channel_id, "message": msg.text}
            if root_id:
                body["root_id"] = root_id
            elif msg.reply_to_message_id:
                body["root_id"] = msg.reply_to_message_id
            if file_ids:
                body["file_ids"] = file_ids

            response = await client.post(f"{base_url}/api/v4/posts", headers=headers, json=body)
            response.raise_for_status()

    # --- receiving, over the socket ---------------------------------------

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """Open the event stream for one bot."""
        existing = self._socket_tasks.get(bot_id)
        if existing is not None and not existing.done():
            logger.info("Mattermost stream already running for bot %s", bot_id)
            return

        self._socket_tasks[bot_id] = asyncio.create_task(
            self._supervise(bot_id, bot_token), name=f"mattermost_ws_{bot_id}"
        )
        logger.info("Started Mattermost event stream for bot %s", bot_id)

    async def stop_polling(self, bot_id: str) -> None:
        task = self._socket_tasks.pop(bot_id, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("Stopped Mattermost event stream for bot %s", bot_id)

    async def _supervise(self, bot_id: str, bot_token: str) -> None:
        """Reconnect on failure. A dropped socket is a bot that stopped
        answering with nothing in the logs to say so."""
        delay = 5.0
        while True:
            try:
                await self._run_stream(bot_id, bot_token)
                delay = 5.0
            except asyncio.CancelledError:
                raise
            except ChannelNotConfigured:
                # An operator has to set the server URL; looping cannot. And
                # `_run_stream` returns without awaiting on that branch, so a
                # retry here spun the event loop at 100% CPU and starved every
                # other task on the process.
                logger.warning("Mattermost stream not started for bot %s", bot_id)
                return
            except Exception:
                logger.exception(
                    "Mattermost stream failed for bot %s, retrying in %.0fs", bot_id, delay
                )
            # Outside the `except`: a session that ends by returning has to
            # yield before the next attempt, or this loop never suspends.
            await asyncio.sleep(delay)
            # Doubled after the wait, not before it: the line logged above names
            # `delay`, and backing off first made it sleep twice what it said.
            # Backs off to a minute so a server that is down for an hour is not
            # hammered 720 times by every bot on it.
            delay = min(delay * 2, 60.0)

    async def _run_stream(self, bot_id: str, bot_token: str) -> None:
        """One authenticated session on the event stream."""
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:
            raise ChannelNotConfigured(
                message=(
                    "The Mattermost event stream needs the 'websockets' package. "
                    "Use webhook mode, or install it."
                ),
                details={"bot_id": bot_id},
            ) from exc

        base_url = self._base_urls.get(bot_id)
        if not base_url:
            raise ChannelNotConfigured(
                message="Mattermost bot has no server URL; cannot open a stream",
                details={"bot_id": bot_id},
            )

        socket_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
        async with connect(f"{socket_url}/api/v4/websocket") as socket:
            await socket.send(
                json.dumps(
                    {
                        "seq": 1,
                        "action": "authentication_challenge",
                        "data": {"token": bot_token},
                    }
                )
            )
            keepalive = asyncio.create_task(self._keepalive(socket))
            try:
                async for frame in socket:
                    await self._on_frame(frame, bot_id)
            finally:
                keepalive.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await keepalive

    async def _keepalive(self, socket: Any) -> None:
        seq = 2
        while True:
            await asyncio.sleep(_PING_SECONDS)
            await socket.send(json.dumps({"seq": seq, "action": "ping"}))
            seq += 1

    async def _on_frame(self, frame: str | bytes, bot_id: str) -> None:
        """Handle one event. A malformed frame is skipped, never fatal."""
        try:
            payload = json.loads(frame)
        except (json.JSONDecodeError, TypeError):
            return
        if payload.get("event") != "posted":
            return

        incoming = self.parse_incoming(payload, bot_id)
        if incoming is None:
            return
        router = ChannelMessageRouter()
        async with get_db_context() as db:
            await router.route(incoming, db)

    # --- receiving, over a webhook ----------------------------------------

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """Mattermost has no API for this: outgoing webhooks are created in its
        own integrations page. Logged so the URL can be pasted there."""
        logger.info(
            "Mattermost: create an outgoing webhook pointing at %s "
            "(System Console → Integrations → Outgoing Webhooks)",
            url,
        )
        return True

    async def delete_webhook(self, bot_token: str) -> bool:
        """Also removed by hand, in the same place."""
        return True

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """Compare the token Mattermost puts in the body.

        Mattermost does not sign the payload the way Slack does - an outgoing
        webhook carries a shared token instead - so this is a bearer check, and
        the token is a credential rather than a signing key. Compared in
        constant time for the same reason every other token here is.
        """
        if not secret or not body:
            return False
        payload = decode_webhook_body(body)
        token = str(payload.get("token", ""))
        return bool(token) and secrets.compare_digest(token, secret)

    # --- normalising -------------------------------------------------------

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """Normalise a `posted` event or an outgoing-webhook body.

        The two arrive in different shapes - the socket nests a JSON *string*
        under `data.post`, the webhook is flat - and everything downstream is
        shared, so the difference stops here.
        """
        if raw_payload.get("event") == "posted":
            return self._from_socket(raw_payload, bot_id)
        return self._from_webhook(raw_payload, bot_id)

    def _from_socket(self, payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        data = payload.get("data") or {}
        try:
            post = json.loads(data.get("post", "{}"))
        except (json.JSONDecodeError, TypeError):
            return None

        # A bot's own posts come back down the same socket. Answering them is an
        # infinite loop with a bill attached.
        props = post.get("props") or {}
        if props.get("from_bot") == "true" or props.get("from_webhook") == "true":
            return None

        attachments = self._attachments(post, bot_id)
        text = (post.get("message") or "").strip()
        if not text and not attachments:
            return None

        root_id = post.get("root_id") or ""
        channel_id = post.get("channel_id", "")
        # "D" is Mattermost's direct-message channel type; anything else is a
        # channel somebody put the bot in.
        channel_type = str(data.get("channel_type") or "")

        return IncomingMessage(
            platform=self.platform,
            bot_id=bot_id,
            platform_user_id=post.get("user_id", ""),
            platform_chat_id=f"{channel_id}:{root_id}" if root_id else channel_id,
            chat_type="private" if channel_type == "D" else "group",
            text=text,
            raw=payload,
            platform_username=data.get("sender_name", "").lstrip("@") or None,
            platform_display_name=data.get("sender_name") or None,
            message_id=post.get("id"),
            attachments=attachments,
        )

    def _attachments(self, post: dict[str, Any], bot_id: str) -> list[IncomingAttachment]:
        """The files on a Mattermost post, as handles.

        A post carries `file_ids` and, on the socket, `metadata.files` with the
        name, size and MIME type beside each. The ids alone would mean a lookup
        per file before anything could be validated, so the metadata is used where
        it is there and an id with none is carried as a handle with nothing
        claimed - which the size check then reads as zero and lets through, to be
        caught against the bytes after the download.
        """
        metadata = (post.get("metadata") or {}).get("files") or []
        described = {str(entry.get("id")): entry for entry in metadata if isinstance(entry, dict)}

        # The handle is the full URL, resolved here from the server this bot's
        # stream was opened against. Every Mattermost deployment is somebody's own
        # server, so the id alone is not enough to fetch anything - and the
        # download signature carries a token, not a bot.
        base_url = self._base_urls.get(bot_id, "")

        found: list[IncomingAttachment] = []
        for file_id in post.get("file_ids") or []:
            entry = described.get(str(file_id), {})
            found.append(
                IncomingAttachment(
                    filename=entry.get("name") or str(file_id),
                    mime_type=entry.get("mime_type") or "application/octet-stream",
                    size=int(entry.get("size") or 0),
                    handle=f"{base_url}/api/v4/files/{file_id}" if base_url else "",
                )
            )
        return found

    async def download_attachment(self, bot_token: str, attachment: IncomingAttachment) -> bytes:
        """Fetch a Mattermost file from the URL the parser resolved.

        Empty means this bot's server was not known when the message arrived - the
        outgoing-webhook path never calls `remember_server` - and that is reported
        rather than guessed at, because guessing a Mattermost address is guessing
        which company's server to send a bot token to.
        """
        if not attachment.handle:
            raise ValueError(
                "This Mattermost bot has no server URL recorded, so its files cannot be fetched."
            )

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                attachment.handle, headers={"Authorization": f"Bearer {bot_token}"}
            )
        response.raise_for_status()
        return response.content

    def _from_webhook(self, payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        text = str(payload.get("text") or "").strip()
        if not text:
            return None
        # Mattermost sends the bot's own posts to an outgoing webhook only when
        # explicitly configured to, but a loop is expensive enough to check for.
        if payload.get("user_name") in {"", None} or str(payload.get("user_id") or "") == "":
            return None

        channel_id = str(payload.get("channel_id") or "")
        channel_name = str(payload.get("channel_name") or "")

        return IncomingMessage(
            platform=self.platform,
            bot_id=bot_id,
            platform_user_id=str(payload.get("user_id") or ""),
            platform_chat_id=channel_id,
            # Mattermost names a direct-message channel after both user ids
            # joined by two underscores; there is no type field in this payload.
            chat_type="private" if "__" in channel_name else "group",
            text=text,
            raw=payload,
            platform_username=str(payload.get("user_name") or "") or None,
            platform_display_name=str(payload.get("user_name") or "") or None,
            message_id=str(payload.get("post_id") or "") or None,
        )
