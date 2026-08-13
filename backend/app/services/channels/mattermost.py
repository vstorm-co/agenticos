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
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx

from app.agents.capabilities.channel_tools import (
    ChannelDetails,
    ChannelDirectoryUnsupported,
    ChannelMember,
    ChannelPost,
    ChannelSummary,
)
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


def _posted_at(create_at: Any) -> datetime | None:
    """A Mattermost timestamp as a datetime, or `None` if it was not one.

    Mattermost counts milliseconds since the epoch. `None` rather than a raise:
    this decorates a line of history, and a post with an unreadable timestamp is
    still a post somebody wrote.
    """
    if not isinstance(create_at, int | float) or not create_at:
        return None
    return datetime.fromtimestamp(create_at / 1000, UTC)


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
        # The live socket per bot, so a typing indicator can be sent on the
        # connection the stream already holds, and the sequence number that
        # connection is up to.
        self._sockets: dict[str, Any] = {}
        # Which account each bot is, so a mention of it can be told from a mention
        # of somebody else. Resolved per stream session - see `_own_user_id`.
        self._own_ids: dict[str, str] = {}
        self._seq: dict[str, int] = {}

    def remember_server(self, bot_id: str, api_base_url: str) -> None:
        """Record which Mattermost server a bot belongs to."""
        self._base_urls[bot_id] = api_base_url.rstrip("/")

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

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Post the message that will become the answer, and return its id."""
        if not msg.api_base_url:
            return None
        channel_id, _, root_id = msg.platform_chat_id.partition(":")
        body: dict[str, Any] = {"channel_id": channel_id, "message": msg.text}
        if root_id:
            body["root_id"] = root_id
        elif msg.reply_to_message_id:
            body["root_id"] = msg.reply_to_message_id

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(
                f"{msg.api_base_url.rstrip('/')}/api/v4/posts",
                headers={"Authorization": f"Bearer {bot_token}"},
                json=body,
            )
        response.raise_for_status()
        post_id = response.json().get("id")
        return str(post_id) if post_id else None

    async def update_reply(self, bot_token: str, msg: OutgoingMessage, handle: str) -> None:
        """Rewrite a post that is already on screen.

        `PATCH` rather than `PUT /posts/{id}`: the full update wants the whole
        post back and would drop anything it was not told about. Mattermost
        broadcasts `post_edited`, so every client watching the channel sees the
        text change without doing anything.
        """
        # Never None in practice - `begin_reply` refused without one and is the
        # only thing that hands out a handle - but the type says otherwise and a
        # crash mid-answer is a worse way to find out.
        base_url = (msg.api_base_url or "").rstrip("/")
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.put(
                f"{base_url}/api/v4/posts/{handle}/patch",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"message": msg.text},
            )
        response.raise_for_status()

    async def typing(self, bot_id: str, msg: OutgoingMessage) -> None:
        """Say the bot is composing, over the socket we already hold.

        Only on the event-stream path: this is a WebSocket action, and a bot
        reached by outgoing webhook has no socket. Nothing is raised in that
        case - the placeholder post says the same thing more durably, and this
        is the decoration on top of it.
        """
        socket = self._sockets.get(bot_id)
        if socket is None:
            return
        channel_id, _, root_id = msg.platform_chat_id.partition(":")
        with contextlib.suppress(Exception):
            await socket.send(
                json.dumps(
                    {
                        "action": "user_typing",
                        "seq": self._next_seq(bot_id),
                        "data": {"channel_id": channel_id, "parent_id": root_id},
                    }
                )
            )

    def _next_seq(self, bot_id: str) -> int:
        """The next sequence number on this bot's socket.

        Mattermost expects them to rise per connection. Kept here rather than in
        `_run_stream` because the keepalive and this both send, and two counters
        on one socket is a protocol error waiting for a busy day.
        """
        self._seq[bot_id] = self._seq.get(bot_id, 1) + 1
        return self._seq[bot_id]

    #
    # Every call here needs `read_channel` on the channel, which a bot holds by
    # being a member of it. That is the permission boundary, it is Mattermost's
    # own, and it is deliberately the only one: an allow-list of our own would
    # be a second answer to "may this bot see this channel", and the two would
    # disagree the first time somebody removed the bot from a channel.

    @staticmethod
    def _server(api_base_url: str | None) -> str:
        """The server to ask, or a refusal a person in the channel can read.

        Raises:
            ChannelDirectoryUnsupported: If the bot has no server URL recorded.
                Reported rather than guessed at, for the same reason
                `download_attachment` refuses: guessing a Mattermost address is
                guessing which company's server to send a bot token to.
        """
        if not api_base_url:
            raise ChannelDirectoryUnsupported(
                "This Mattermost bot has no server URL recorded, so nothing about "
                "the channel can be looked up."
            )
        return api_base_url.rstrip("/")

    @staticmethod
    def _display_name(user: dict[str, Any]) -> str | None:
        """What a person is called, preferring what they chose to be called."""
        full = " ".join(
            part for part in (user.get("first_name"), user.get("last_name")) if part
        ).strip()
        return user.get("nickname") or full or None

    async def channel_details(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None
    ) -> ChannelDetails:
        """`GET /channels/{id}`, with the member count from `/stats` beside it."""
        base_url = self._server(api_base_url)
        headers = {"Authorization": f"Bearer {bot_token}"}
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            channel = await client.get(f"{base_url}/api/v4/channels/{channel_id}", headers=headers)
            channel.raise_for_status()
            stats = await client.get(
                f"{base_url}/api/v4/channels/{channel_id}/stats", headers=headers
            )
            stats.raise_for_status()

        found = channel.json()
        member_count = stats.json().get("member_count")
        return ChannelDetails(
            channel_id=str(found.get("id") or channel_id),
            name=self._channel_name(found, channel_id),
            purpose=str(found.get("purpose") or "") or None,
            # Mattermost calls it `header`; the contract calls it `topic`,
            # because Slack does and one of the two names had to win.
            topic=str(found.get("header") or "") or None,
            # "O" is an open channel; everything else - private, direct, group -
            # is somewhere not everyone can walk into.
            is_private=found.get("type") != "O",
            member_count=None if member_count is None else int(member_count),
        )

    @staticmethod
    def _channel_name(found: dict[str, Any], channel_id: str) -> str:
        """What to call this channel to somebody reading a reply.

        `display_name` is what people see in the sidebar and `name` is the URL
        slug, so the slug is the fallback - a model quoting it reads as a typo.

        Except in a direct or group message, where Mattermost leaves
        `display_name` empty and names the channel after the user ids joined by
        two underscores. Handing an agent
        `cm36shpzrpnt9jmc5hzcerkjie__wz75u9w6zjba7dn7jwf4aush5y` as "the channel
        you are in" is worse than telling it nothing, and it is what
        `{channel_name}` filled in until this existed.
        """
        kind = str(found.get("type") or "")
        if kind == "D":
            return "a direct message"
        if kind == "G":
            return "a group message"
        return str(found.get("display_name") or found.get("name") or channel_id)

    async def channel_members(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None, limit: int
    ) -> list[ChannelMember]:
        """`GET /channels/{id}/members`, resolved to names in one `/users/ids` call.

        Two requests rather than one per member: a channel of forty people would
        otherwise be forty round trips inside a tool call, on a bot somebody is
        waiting for.
        """
        base_url = self._server(api_base_url)
        headers = {"Authorization": f"Bearer {bot_token}"}
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            members = await client.get(
                f"{base_url}/api/v4/channels/{channel_id}/members",
                headers=headers,
                params={"per_page": limit},
            )
            members.raise_for_status()
            memberships = {
                str(entry.get("user_id")): str(entry.get("roles") or "") for entry in members.json()
            }
            if not memberships:
                return []

            users = await client.post(
                f"{base_url}/api/v4/users/ids", headers=headers, json=sorted(memberships)
            )
            users.raise_for_status()

        return [
            ChannelMember(
                user_id=str(user.get("id")),
                username=str(user.get("username") or "") or None,
                display_name=self._display_name(user),
                is_bot=bool(user.get("is_bot")),
                role=(
                    "admin"
                    if "channel_admin" in memberships.get(str(user.get("id")), "")
                    else "member"
                ),
            )
            for user in users.json()
        ]

    async def search_channels(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None, query: str, limit: int
    ) -> list[ChannelSummary]:
        """`POST /teams/{team_id}/channels/search`, in this channel's own team.

        Team-scoped rather than the server-wide `POST /channels/search`, which
        needs system-administrator rights: a bot searching every team on
        somebody's Mattermost is a wider answer than the question deserves, and
        one most deployments would refuse outright.
        """
        base_url = self._server(api_base_url)
        headers = {"Authorization": f"Bearer {bot_token}"}
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            channel = await client.get(f"{base_url}/api/v4/channels/{channel_id}", headers=headers)
            channel.raise_for_status()
            team_id = str(channel.json().get("team_id") or "")
            if not team_id:
                # A direct or group message belongs to no team, so there is no
                # scope to search from here. Said rather than answered with an
                # empty list, which would read as "no such channel".
                raise ChannelDirectoryUnsupported(
                    "This is a direct message, which is not in a team - there is no "
                    "channel list to search from here."
                )

            found = await client.post(
                f"{base_url}/api/v4/teams/{team_id}/channels/search",
                headers=headers,
                json={"term": query},
            )
            found.raise_for_status()

        return [
            ChannelSummary(
                channel_id=str(entry.get("id")),
                name=str(entry.get("display_name") or entry.get("name") or ""),
                purpose=str(entry.get("purpose") or "") or None,
                is_private=entry.get("type") != "O",
            )
            for entry in found.json()[:limit]
        ]

    async def channel_history(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None, limit: int
    ) -> list[ChannelPost]:
        """`GET /channels/{id}/posts`, newest last and without the system noise.

        Mattermost returns `order` newest first and a `posts` map beside it, so
        the order is reversed here - a model reading a conversation top to bottom
        gets it the way a person would.
        """
        base_url = self._server(api_base_url)
        headers = {"Authorization": f"Bearer {bot_token}"}
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{base_url}/api/v4/channels/{channel_id}/posts",
                headers=headers,
                params={"per_page": limit},
            )
            response.raise_for_status()
            payload = response.json()
            posts = payload.get("posts") or {}
            order = [
                post_id
                for post_id in reversed(payload.get("order") or [])
                # "somebody joined the channel" is not what was said in it.
                if not str((posts.get(post_id) or {}).get("type") or "").startswith("system_")
            ]
            if not order:
                return []

            authors = await client.post(
                f"{base_url}/api/v4/users/ids",
                headers=headers,
                json=sorted({str(posts[post_id].get("user_id")) for post_id in order}),
            )
            authors.raise_for_status()

        named = {
            str(user.get("id")): str(user.get("username") or user.get("id"))
            for user in authors.json()
        }
        return [
            ChannelPost(
                author=named.get(str(posts[post_id].get("user_id")), "unknown"),
                text=str(posts[post_id].get("message") or ""),
                posted_at=_posted_at(posts[post_id].get("create_at")),
            )
            for post_id in order
        ]

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

    async def _own_user_id(self, bot_id: str, bot_token: str) -> str | None:
        """Which Mattermost account this bot *is*, so a mention of it is legible.

        Resolved once per stream session rather than per message, and stored beside
        the base URL because it is the same kind of per-bot fact. `None` when the
        server would not say: the caller then treats every post as addressed, which
        is the behaviour a bot had before this existed - answering too much is a
        worse failure than answering too little only where somebody chose it.
        """
        base_url = self._base_urls.get(bot_id)
        if not base_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.get(
                    f"{base_url}/api/v4/users/me",
                    headers={"Authorization": f"Bearer {bot_token}"},
                )
            response.raise_for_status()
            return str(response.json().get("id") or "") or None
        except Exception:
            logger.warning("mattermost_own_id_unresolved", extra={"bot_id": bot_id}, exc_info=True)
            return None

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
            self._sockets[bot_id] = socket
            # Before the first frame is read, so no post is judged against an
            # unknown identity - a miss there would answer a channel it should
            # have stayed out of.
            own = await self._own_user_id(bot_id, bot_token)
            if own is not None:
                self._own_ids[bot_id] = own
            keepalive = asyncio.create_task(self._keepalive(socket))
            try:
                async for frame in socket:
                    await self._on_frame(frame, bot_id)
            finally:
                self._sockets.pop(bot_id, None)
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
            addressed=self._addressed(data, bot_id),
        )

    def _addressed(self, data: dict[str, Any], bot_id: str) -> bool | None:
        """Whether this post named the bot, from the event's own mention list.

        Mattermost puts the mentioned account ids in `data.mentions`, as JSON in a
        string. Read from there rather than from the text: `@ada` is a mention of
        somebody whose display name the bot cannot resolve, and matching on text
        would make a bot called `bot` answer the word "robot".

        `None` where the bot's own id was never resolved, which the router reads as
        "the platform did not say" and answers as it did before. A *missing*
        `mentions` key with a known id is `False`: the event carries the list
        whenever there is one, so its absence means nobody was mentioned.
        """
        own = self._own_ids.get(bot_id)
        if own is None:
            return None
        raw = data.get("mentions")
        if raw is None:
            return False
        try:
            mentioned = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return False
        return own in mentioned if isinstance(mentioned, list) else False

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
