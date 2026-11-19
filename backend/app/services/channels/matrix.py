"""Matrix channel adapter (#2081).

The Client-Server API spoken directly over `httpx`, the way the Discord and
Mattermost adapters speak theirs: what a bot needs is a long-poll, a send and an
edit, and an SDK would bring its own sync loop, store and retry logic to sit
beside the ones this package already has.

**Stream only.** Everything arrives over the bot's `/sync` long-poll, so a
deployment needs no public address for Matrix; homeservers have no outgoing
webhook to offer anyway. One long-poll per bot across every worker, held by the
stream lease. The position it has read up to (`next_batch`) is kept in the shared
Redis after each batch, so a restart resumes where the last one stopped; the very
first sync of an account skips the backlog rather than answering it.

**The bot is an ordinary account** on the organization's own homeserver, reached
with its access token (sealed in the vault) and the homeserver's address
(`api_base_url`). `/whoami` is asked when the stream opens: a token the server
rejects stops the bot with a reason instead of being retried for ever.

**Conversations.** A thread is a conversation: a question at the top of a room
is answered in a thread rooted at it, and a reply in that thread continues it.
In a room the bot answers a message that mentions it, or any message in a thread
it was asked in; in a direct chat - a room of two - it answers everything. It
joins a room when invited by somebody its access policy admits.

**What is posted is model output**, so nothing the bot posts may notify anybody
(an empty `m.mentions`), and an answer is only ever written by editing the
message the router opened - never streamed raw - so a guardrail's redaction
holds here as everywhere (#1900). Approvals and questions are numbered replies
(`sms_prompts`): Matrix has no buttons, and polls are not in the spec.

**No end-to-end encryption yet.** An encrypted room delivers nothing this
adapter can read; that is the second stage of #2081.
"""

import asyncio
import contextlib
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx

from app.agents.capabilities.channel_tools import (
    ChannelDetails,
    ChannelDirectoryUnsupported,
    ChannelMember,
    ChannelPost,
)
from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.services.channels import connection_state, sms_prompts
from app.services.channels.base import (
    REACTION_EMOJI,
    ChannelAdapter,
    IncomingAttachment,
    IncomingMessage,
    IncomingPress,
    OutgoingAttachment,
    OutgoingMessage,
    PromptMessage,
    channel_key,
    mentionable_text,
    split_thread,
    supervise_stream,
    thread_key,
)
from app.services.channels.discord_protocol import Recent
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.matrix_protocol import (
    CLIENT_API,
    MEDIA_UPLOAD,
    RELATIONS_API,
    SYNC_FILTER,
    SYNC_TIMEOUT_MS,
    Message,
    attachment_of,
    chunks,
    edit_content,
    error_code,
    file_content,
    names,
    reaction_content,
    read_message,
    retry_after,
    room_key,
    room_of,
    text_content,
    with_latest_edit,
    without_mention,
)

logger = logging.getLogger(__name__)

PLATFORM = "matrix"

_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_SYNC_TIMEOUT = httpx.Timeout(SYNC_TIMEOUT_MS / 1000 + 30.0, connect=10.0)
"""The long-poll's own wait plus room for a slow answer."""

_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_CEILING = 30.0
"""Seconds; a homeserver asking for longer is down for this answer's purposes."""

_CACHE_SIZE = 4096
_ACCESS_SECONDS = 60.0
"""How long a worker trusts a bot's homeserver and token read from its row."""

_SINCE_TTL_SECONDS = 30 * 24 * 60 * 60
"""How long a quiet bot's place in its sync stream is kept."""

_REJECTED_TOKEN = frozenset({"M_UNKNOWN_TOKEN", "M_MISSING_TOKEN", "M_USER_DEACTIVATED"})

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client the sync position is kept in, or withdraw it."""
    global _redis
    _redis = redis


def _since_key(bot_id: str, user_id: str) -> str:
    # Keyed on the account as well: a token for another account must not resume
    # from a position that was never its own.
    return f"channel:matrix:since:{bot_id}:{hashlib.sha256(user_id.encode()).hexdigest()}"


@dataclass(frozen=True)
class _Account:
    """Who a bot is on its homeserver."""

    user_id: str
    display_name: str | None


@dataclass
class _Reply:
    """An answer being written, which may run past one message."""

    room_id: str
    root: str | None
    ids: list[str]
    shown: list[str] = field(default_factory=list)


def _segment(value: str) -> str:
    """One path segment: room ids, event ids and user ids carry `!`, `$`, `@` and `:`."""
    return quote(value, safe="")


def _posted_at(timestamp: int | None) -> datetime | None:
    return None if timestamp is None else datetime.fromtimestamp(timestamp / 1000, UTC)


def _rejected(response: httpx.Response) -> bool:
    return response.status_code == 401 or error_code(response) in _REJECTED_TOKEN


class MatrixAdapter(ChannelAdapter):
    """Matrix, over the Client-Server API v3."""

    platform: str = PLATFORM

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(timeout=_HTTP_TIMEOUT, transport=transport)
        self._sync_tasks: dict[str, asyncio.Task[None]] = {}
        # Per bot, registered before its stream opens: the adapter is one object
        # serving every bot, and the homeserver is each bot's own.
        self._servers: dict[str, str] = {}
        self._accounts: dict[str, _Account] = {}
        # Calls that name only the bot - a reaction, a typing notice - run in
        # workers that never opened its stream, so they read its row.
        self._access: dict[str, tuple[str, str, float]] = {}
        self._whoami: Recent[_Account] = Recent(_CACHE_SIZE)
        self._direct: Recent[bool] = Recent(_CACHE_SIZE)
        self._bot_threads: Recent[bool] = Recent(_CACHE_SIZE)
        self._replies: Recent[_Reply] = Recent(_CACHE_SIZE)

    def prepare_connection(
        self,
        bot_id: str,
        *,
        api_base_url: str | None,
        app_token: str | None,
        approved_guild_ids: tuple[str, ...] = (),
    ) -> None:
        if api_base_url:
            self._servers[bot_id] = api_base_url.rstrip("/")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(
        self,
        method: str,
        url: str,
        token: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        """One request, waiting out the homeserver's rate limit a few times.

        A streamed answer edits once a second, which a homeserver's default
        message rate limit does not allow for long; the 429 says how long to wait.
        Bots that stream answers want a rate-limit exemption on their homeserver,
        which `docs/channels.md` explains.
        """
        headers = {"Authorization": f"Bearer {token}"}
        if content_type is not None:
            headers["Content-Type"] = content_type
        attempt = 0
        while True:
            response = await self._http.request(
                method,
                url,
                headers=headers,
                json=body,
                params=params,
                content=content,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
            if response.status_code != 429 or attempt == _RATE_LIMIT_RETRIES:
                return response
            attempt += 1
            await asyncio.sleep(min(retry_after(response), _RATE_LIMIT_CEILING))

    async def _send(
        self, base_url: str, token: str, room_id: str, event_type: str, content: dict[str, Any]
    ) -> str:
        """Send one event and return its id. The transaction id makes a retry idempotent."""
        response = await self._call(
            "PUT",
            f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/send/{event_type}/{uuid4().hex}",
            token,
            body=content,
        )
        response.raise_for_status()
        return str(response.json()["event_id"])

    async def _upload(self, base_url: str, token: str, item: OutgoingAttachment) -> str:
        response = await self._call(
            "POST",
            f"{base_url}{MEDIA_UPLOAD}",
            token,
            params={"filename": item.filename},
            content=item.content,
            content_type=item.mime_type,
        )
        response.raise_for_status()
        return str(response.json()["content_uri"])

    @staticmethod
    def _base(api_base_url: str | None) -> str:
        if not api_base_url:
            raise ValueError("Matrix bot has no homeserver URL. Set it on the bot before sending.")
        return api_base_url.rstrip("/")

    @staticmethod
    def _directory_base(api_base_url: str | None) -> str:
        """The homeserver to ask, or a refusal a person in the room can read."""
        if not api_base_url:
            raise ChannelDirectoryUnsupported(
                "This Matrix bot has no homeserver URL recorded, so nothing about the room "
                "can be looked up."
            )
        return api_base_url.rstrip("/")

    @staticmethod
    def _room(key: str) -> str:
        try:
            return room_of(key)
        except ValueError:
            raise ChannelDirectoryUnsupported("Use a Matrix room this bot is in") from None

    async def _bot_access(self, bot_id: str) -> tuple[str, str]:
        """A bot's homeserver and token, for a call that names only the bot.

        Read from the row and kept for a minute: a worker that never opened the
        bot's stream was never told either, and an edit to the bot reaches every
        worker within that minute.

        Raises:
            ChannelNotConfigured: If the bot is gone, paused or has no homeserver.
        """
        cached = self._access.get(bot_id)
        if cached is not None and time.monotonic() - cached[2] < _ACCESS_SECONDS:
            return cached[0], cached[1]
        from app.db.session import get_db_context
        from app.repositories import channel_bot_repo
        from app.services.channel_bot import unseal_bot_token

        async with get_db_context() as db:
            bot = await channel_bot_repo.get_for_inbound(db, UUID(bot_id))
            if bot is None or bot.platform != PLATFORM or not bot.api_base_url:
                raise ChannelNotConfigured(
                    message="This Matrix bot has no homeserver URL", details={"bot_id": bot_id}
                )
            base_url, token = bot.api_base_url.rstrip("/"), unseal_bot_token(bot)
        self._access[bot_id] = (base_url, token, time.monotonic())
        return base_url, token

    async def _account(self, base_url: str, token: str) -> _Account:
        """Who a token belongs to, asked once per token.

        Raises:
            ChannelNotConfigured: If the homeserver rejects the token - a retry
                will not change that, an operator entering a new one will.
        """
        key = hashlib.sha256(f"{base_url}\n{token}".encode()).hexdigest()
        known = self._whoami.get(key)
        if known is not None:
            return known
        response = await self._call("GET", f"{base_url}{CLIENT_API}/account/whoami", token)
        if _rejected(response):
            raise ChannelNotConfigured(
                message=(
                    "The homeserver rejected the Matrix access token. Enter a valid "
                    "token for the bot account."
                )
            )
        response.raise_for_status()
        user_id = str(response.json()["user_id"])
        profile = await self._call(
            "GET", f"{base_url}{CLIENT_API}/profile/{_segment(user_id)}/displayname", token
        )
        name = profile.json().get("displayname") if profile.status_code == 200 else None
        account = _Account(user_id=user_id, display_name=name if isinstance(name, str) else None)
        self._whoami.put(key, account)
        return account

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Post a reply in its thread, in as many messages as it takes, files after the text."""
        base_url = self._base(msg.api_base_url)
        key, root = split_thread(msg.platform_chat_id)
        room_id = room_of(key)
        sent: str | None = None
        for piece in chunks(msg.text):
            if piece.strip():
                sent = await self._send(
                    base_url, bot_token, room_id, "m.room.message", text_content(piece, root=root)
                )
        files = list(msg.attachments)
        if msg.image_png is not None:
            files.insert(
                0,
                OutgoingAttachment(
                    filename=msg.image_filename, content=msg.image_png, mime_type="image/png"
                ),
            )
        for item in files:
            uri = await self._upload(base_url, bot_token, item)
            sent = await self._send(
                base_url,
                bot_token,
                room_id,
                "m.room.message",
                file_content(item.filename, item.mime_type, len(item.content), uri, root=root),
            )
        return sent

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Post the message the answer will be written into, and return its id."""
        base_url = self._base(msg.api_base_url)
        key, root = split_thread(msg.platform_chat_id)
        room_id = room_of(key)
        shown = chunks(msg.text)[0] or "…"
        event_id = await self._send(
            base_url, bot_token, room_id, "m.room.message", text_content(shown, root=root)
        )
        self._replies.put(
            event_id, _Reply(room_id=room_id, root=root or None, ids=[event_id], shown=[shown])
        )
        return event_id

    async def update_reply(self, bot_token: str, msg: OutgoingMessage, handle: str) -> None:
        """Rewrite the answer with `m.replace` edits, spilling past `MESSAGE_LIMIT`.

        Each message is edited only when its part changed, and a part the answer
        no longer reaches is redacted - an output guardrail can shorten the
        answer at the end.
        """
        base_url = self._base(msg.api_base_url)
        reply = self._replies.get(handle)
        if reply is None:
            # Another worker opened it, or this one restarted.
            key, root = split_thread(msg.platform_chat_id)
            reply = _Reply(room_id=room_of(key), root=root or None, ids=[handle], shown=[""])
            self._replies.put(handle, reply)
        pieces = [piece or "…" for piece in chunks(msg.text)]
        for index, piece in enumerate(pieces):
            if index < len(reply.ids):
                if reply.shown[index] != piece:
                    await self._send(
                        base_url,
                        bot_token,
                        reply.room_id,
                        "m.room.message",
                        edit_content(piece, target=reply.ids[index]),
                    )
                    reply.shown[index] = piece
            else:
                reply.ids.append(
                    await self._send(
                        base_url,
                        bot_token,
                        reply.room_id,
                        "m.room.message",
                        text_content(piece, root=reply.root),
                    )
                )
                reply.shown.append(piece)
        while len(reply.ids) > len(pieces):
            stale = reply.ids.pop()
            reply.shown.pop()
            response = await self._call(
                "PUT",
                f"{base_url}{CLIENT_API}/rooms/{_segment(reply.room_id)}/redact/"
                f"{_segment(stale)}/{uuid4().hex}",
                bot_token,
                body={},
            )
            response.raise_for_status()

    async def send_prompt(self, bot_token: str, prompt: PromptMessage) -> None:
        """An approval or a question as numbered lines, answered by replying with a number.

        Reserved before it is sent, so two workers never hand out the same
        numbers; `sms_prompts.answer` reads a reply back into the press it stands
        for, in the same thread.
        """
        start = await sms_prompts.reserve(
            prompt.bot_id, prompt.platform_chat_id, len(prompt.choices), platform=PLATFORM
        )
        lines = [f"{number}. {choice.label}" for number, choice in enumerate(prompt.choices, start)]
        await self.send_message(
            bot_token,
            OutgoingMessage(
                platform_chat_id=prompt.platform_chat_id,
                text=f"{prompt.text}\n\n" + "\n".join(lines) + "\n\nReply with just the number.",
                api_base_url=prompt.api_base_url,
            ),
        )
        await sms_prompts.remember(
            prompt.bot_id,
            prompt.platform_chat_id,
            [choice.value for choice in prompt.choices],
            start=start,
            platform=PLATFORM,
        )

    async def settle_prompt(self, bot_token: str, press: IncomingPress, text: str) -> None:
        """Say what was chosen, and stop the prompt's numbers answering."""
        await sms_prompts.settle(
            press.bot_id, press.platform_chat_id, press.value, platform=PLATFORM
        )
        base_url, _ = await self._bot_access(press.bot_id)
        await self.send_message(
            bot_token,
            OutgoingMessage(
                platform_chat_id=press.platform_chat_id, text=text, api_base_url=base_url
            ),
        )

    async def acknowledge_message(
        self, bot_token: str, incoming: IncomingMessage, reaction: str
    ) -> None:
        """React to the question as it arrives, so the asker sees it was heard (#2084)."""
        if incoming.message_id is None:
            return
        symbol = REACTION_EMOJI.get(reaction)
        if symbol is None:
            raise ValueError(f"'{reaction}' is not a reaction this bot can send on Matrix")
        base_url, _ = await self._bot_access(incoming.bot_id)
        await self._send(
            base_url,
            bot_token,
            room_of(channel_key(incoming.platform_chat_id)),
            "m.reaction",
            reaction_content(incoming.message_id, symbol),
        )

    async def react_to_message(
        self,
        bot_token: str,
        channel_id: str,
        message_id: str,
        emoji: str,
        *,
        api_base_url: str | None,
    ) -> None:
        base_url = self._directory_base(api_base_url)
        symbol = REACTION_EMOJI.get(emoji)
        if symbol is None:
            raise ChannelDirectoryUnsupported("Choose a supported standard emoji name")
        room_id = self._room(channel_id)
        target = await self._call(
            "GET",
            f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/event/{_segment(message_id)}",
            bot_token,
        )
        if target.status_code == 404 or (
            target.is_success and target.json().get("room_id") != room_id
        ):
            raise ChannelDirectoryUnsupported("The selected message does not belong to this room")
        target.raise_for_status()
        await self._send(
            base_url, bot_token, room_id, "m.reaction", reaction_content(message_id, symbol)
        )

    async def typing(self, bot_id: str, msg: OutgoingMessage) -> None:
        """Say the bot is composing in the room, for up to thirty seconds.

        Never fatal, as the base contract says: the placeholder says the same
        thing more durably. A failure is logged, not raised.
        """
        try:
            base_url, token = await self._bot_access(bot_id)
            account = await self._account(base_url, token)
            room_id = room_of(channel_key(msg.platform_chat_id))
            response = await self._call(
                "PUT",
                f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/typing/"
                f"{_segment(account.user_id)}",
                token,
                body={"typing": True, "timeout": 30_000},
            )
            response.raise_for_status()
        except Exception:
            logger.warning("matrix_typing_failed", extra={"bot_id": bot_id}, exc_info=True)

    async def download_attachment(self, bot_token: str, attachment: IncomingAttachment) -> bytes:
        """Fetch a file over authenticated media, from the URL the parser resolved.

        Read no further than the upload limit: the claimed size is what the
        sender's client wrote, not a measurement.
        """
        if not attachment.handle:
            raise ValueError("This Matrix file has no address to fetch it from.")
        limit = settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if attachment.size > limit:
            raise ValueError("The Matrix file exceeds the upload limit")
        received = bytearray()
        async with self._http.stream(
            "GET",
            attachment.handle,
            headers={"Authorization": f"Bearer {bot_token}"},
            follow_redirects=True,
        ) as response:
            response.raise_for_status()
            async for part in response.aiter_bytes():
                received.extend(part)
                if len(received) > limit:
                    raise ValueError("The Matrix file exceeds the upload limit")
        return bytes(received)

    async def _joined(self, base_url: str, token: str, room_id: str) -> dict[str, Any]:
        response = await self._call(
            "GET", f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/joined_members", token
        )
        if response.status_code == 403:
            raise ChannelDirectoryUnsupported("This bot is not in that Matrix room")
        response.raise_for_status()
        joined = response.json().get("joined")
        return joined if isinstance(joined, dict) else {}

    async def is_channel_member(
        self, bot_token: str, channel_id: str, platform_user_id: str, *, api_base_url: str | None
    ) -> bool:
        joined = await self._joined(
            self._directory_base(api_base_url), bot_token, self._room(channel_id)
        )
        return platform_user_id in joined

    async def channel_members(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None, limit: int
    ) -> list[ChannelMember]:
        base_url = self._directory_base(api_base_url)
        own = await self._account(base_url, bot_token)
        joined = await self._joined(base_url, bot_token, self._room(channel_id))
        return [
            ChannelMember(
                user_id=user_id,
                username=user_id,
                display_name=profile.get("display_name") if isinstance(profile, dict) else None,
                is_bot=user_id == own.user_id,
            )
            for user_id, profile in list(joined.items())[:limit]
        ]

    async def _state(
        self, base_url: str, token: str, room_id: str, event_type: str
    ) -> dict[str, Any]:
        """One state event's content, empty when the room has none."""
        response = await self._call(
            "GET",
            f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/state/{event_type}/",
            token,
        )
        if response.status_code == 404:
            return {}
        if response.status_code == 403:
            raise ChannelDirectoryUnsupported("This bot is not in that Matrix room")
        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, dict) else {}

    async def channel_details(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None
    ) -> ChannelDetails:
        base_url = self._directory_base(api_base_url)
        room_id = self._room(channel_id)
        name = (await self._state(base_url, bot_token, room_id, "m.room.name")).get("name")
        topic = (await self._state(base_url, bot_token, room_id, "m.room.topic")).get("topic")
        rule = (await self._state(base_url, bot_token, room_id, "m.room.join_rules")).get(
            "join_rule"
        )
        joined = await self._joined(base_url, bot_token, room_id)
        return ChannelDetails(
            channel_id=channel_id,
            name=name if isinstance(name, str) and name else room_id,
            topic=topic if isinstance(topic, str) else None,
            is_private=rule != "public",
            member_count=len(joined),
        )

    async def _thread_events(
        self, base_url: str, token: str, room_id: str, root: str, limit: int
    ) -> list[dict[str, Any]]:
        """A thread's root and replies, oldest first, the newest `limit` of them."""
        room = _segment(room_id)
        replies = await self._call(
            "GET",
            f"{base_url}{RELATIONS_API}/rooms/{room}/relations/{_segment(root)}/m.thread",
            token,
            params={"dir": "b", "limit": limit},
        )
        if replies.status_code == 403:
            raise ChannelDirectoryUnsupported("This bot is not in that Matrix room")
        replies.raise_for_status()
        events: list[dict[str, Any]] = list(reversed(replies.json().get("chunk") or []))
        first = await self._call(
            "GET", f"{base_url}{CLIENT_API}/rooms/{room}/event/{_segment(root)}", token
        )
        if first.is_success:
            events.insert(0, first.json())
        elif first.status_code != 404:
            first.raise_for_status()
        return events[-limit:] if limit > 0 else []

    async def channel_history(
        self,
        bot_token: str,
        channel_id: str,
        *,
        api_base_url: str | None,
        limit: int,
        thread_id: str | None = None,
    ) -> list[ChannelPost]:
        """The recent transcript, newest last, each message as its latest edit says.

        A thread is read through its relations and a room through `/messages`:
        they are two transcripts, and the agent answering in a thread is in the
        thread.
        """
        base_url = self._directory_base(api_base_url)
        room_id = self._room(channel_id)
        if thread_id:
            events = await self._thread_events(base_url, bot_token, room_id, thread_id, limit)
        else:
            response = await self._call(
                "GET",
                f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/messages",
                bot_token,
                params={
                    "dir": "b",
                    "limit": limit,
                    "filter": '{"types":["m.room.message"]}',
                },
            )
            if response.status_code == 403:
                raise ChannelDirectoryUnsupported("This bot is not in that Matrix room")
            response.raise_for_status()
            events = list(reversed(response.json().get("chunk") or []))[-limit:]
        posts: list[ChannelPost] = []
        for event in events:
            message = read_message(with_latest_edit(event))
            if message is None:
                continue
            posts.append(
                ChannelPost(
                    author=message.sender,
                    text=message.text or (message.attachment[0] if message.attachment else ""),
                    posted_at=_posted_at(message.origin_server_ts),
                    post_id=message.event_id,
                    author_id=message.sender,
                )
            )
        return posts

    async def thread_attachments(
        self,
        bot_token: str,
        channel_id: str,
        *,
        thread_id: str,
        api_base_url: str | None,
        limit: int,
    ) -> list[IncomingAttachment]:
        """The files posted in a thread before the bot was asked, oldest first.

        Its own uploads are left out: feeding a chart it drew back to it would
        have the agent answering about its own output.
        """
        base_url = self._directory_base(api_base_url)
        own = await self._account(base_url, bot_token)
        found: list[IncomingAttachment] = []
        for event in await self._thread_events(
            base_url, bot_token, self._room(channel_id), thread_id, limit
        ):
            message = read_message(event)
            if message is None or message.sender == own.user_id:
                continue
            attachment = attachment_of(message, base_url)
            if attachment is not None:
                found.append(attachment)
        return found

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """Open the bot's `/sync` long-poll."""
        existing = self._sync_tasks.get(bot_id)
        if existing is not None and not existing.done():
            logger.info("Matrix sync already running for bot %s", bot_id)
            return
        self._sync_tasks[bot_id] = asyncio.create_task(
            self._supervise(bot_id, bot_token), name=f"matrix_sync_{bot_id}"
        )
        logger.info("Started Matrix sync for bot %s", bot_id)

    async def stop_polling(self, bot_id: str) -> None:
        task = self._sync_tasks.pop(bot_id, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # A token or a homeserver may have changed; the next session asks again.
        self._accounts.pop(bot_id, None)
        self._access.pop(bot_id, None)
        logger.info("Stopped Matrix sync for bot %s", bot_id)

    async def _supervise(self, bot_id: str, bot_token: str) -> None:
        await supervise_stream(
            bot_id,
            platform="Matrix sync",
            session=lambda: self._run_stream(bot_id, bot_token),
            failing=(
                "The Matrix sync keeps failing. Check that the deployment can reach the "
                "homeserver and the access token is still valid."
            ),
        )

    async def _run_stream(self, bot_id: str, bot_token: str) -> None:
        """One session of long-polls, from the stored position, until one fails."""
        base_url = self._servers.get(bot_id)
        if not base_url:
            raise ChannelNotConfigured(
                message="Matrix bot has no homeserver URL; set it on the bot.",
                details={"bot_id": bot_id},
            )
        account = await self._account(base_url, bot_token)
        self._accounts[bot_id] = account
        await connection_state.record_up(bot_id)
        beat = asyncio.create_task(connection_state.heartbeat(bot_id))
        try:
            since = await self._load_since(bot_id, account.user_id)
            while True:
                batch = await self._sync(base_url, bot_token, since)
                await self._on_sync(
                    bot_id, bot_token, base_url, account, batch, backlog=since is None
                )
                since = str(batch["next_batch"])
                await self._store_since(bot_id, account.user_id, since)
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    async def _sync(self, base_url: str, token: str, since: str | None) -> dict[str, Any]:
        params: dict[str, str | int] = {"filter": SYNC_FILTER, "timeout": 0}
        if since is not None:
            params = {"filter": SYNC_FILTER, "since": since, "timeout": SYNC_TIMEOUT_MS}
        response = await self._call(
            "GET", f"{base_url}{CLIENT_API}/sync", token, params=params, timeout=_SYNC_TIMEOUT
        )
        if _rejected(response):
            raise ChannelNotConfigured(
                message=(
                    "The homeserver rejected the Matrix access token. Enter a valid "
                    "token for the bot account."
                )
            )
        response.raise_for_status()
        return response.json()

    @staticmethod
    async def _load_since(bot_id: str, user_id: str) -> str | None:
        return None if _redis is None else await _redis.get(_since_key(bot_id, user_id))

    @staticmethod
    async def _store_since(bot_id: str, user_id: str, since: str) -> None:
        if _redis is not None:
            await _redis.set(_since_key(bot_id, user_id), since, ttl=_SINCE_TTL_SECONDS)

    async def _on_sync(
        self,
        bot_id: str,
        token: str,
        base_url: str,
        account: _Account,
        batch: dict[str, Any],
        *,
        backlog: bool,
    ) -> None:
        """Handle one sync batch: invitations, departures, then each room's new messages.

        `backlog` is the account's first sync, whose timeline is history: the bot
        joins nothing late and answers none of it.
        """
        rooms = batch.get("rooms") or {}
        for room_id, invited in (rooms.get("invite") or {}).items():
            await self._on_invite(bot_id, token, base_url, account, room_id, invited)
        for room_id in rooms.get("leave") or {}:
            self._direct.pop(f"{bot_id}:{room_id}")
        for room_id, joined in (rooms.get("join") or {}).items():
            events = (joined.get("timeline") or {}).get("events") or []
            if any(event.get("type") == "m.room.member" for event in events):
                # Somebody joined or left, so a room of two may no longer be one.
                self._direct.pop(f"{bot_id}:{room_id}")
            if backlog:
                continue
            for event in events:
                if event.get("type") != "m.room.message" or event.get("sender") == account.user_id:
                    continue
                direct = await self._is_direct(bot_id, token, base_url, room_id)
                incoming = self.parse_incoming(
                    {
                        "room_id": room_id,
                        "event": event,
                        "direct": direct,
                        "bot_thread": not direct
                        and await self._in_bot_thread(
                            bot_id, token, base_url, account, room_id, event
                        ),
                    },
                    bot_id,
                )
                if incoming is None:
                    continue
                from app.services.channels.ingress import admit_message

                await admit_message(incoming)

    async def _is_direct(self, bot_id: str, token: str, base_url: str, room_id: str) -> bool:
        """Whether a room holds the bot and one other person, and nobody else.

        A room is the conservative reading: a group taken for a private chat would
        read the speaker's private memory into an answer the room sees (#1470), so
        a room whose members cannot be counted is a room.
        """
        key = f"{bot_id}:{room_id}"
        known = self._direct.get(key)
        if known is not None:
            return known
        try:
            direct = len(await self._joined(base_url, token, room_id)) == 2
        except httpx.HTTPError, ChannelDirectoryUnsupported:
            logger.warning("matrix_members_unread", extra={"bot_id": bot_id}, exc_info=True)
            return False
        self._direct.put(key, direct)
        return direct

    async def _in_bot_thread(
        self,
        bot_id: str,
        token: str,
        base_url: str,
        account: _Account,
        room_id: str,
        event: dict[str, Any],
    ) -> bool:
        """Whether a message is in a thread the bot was asked in, or opened.

        Read off the thread's root - the bot's own message, or one that mentions
        it - and remembered, so a busy thread costs one lookup.
        """
        message = read_message(event)
        if message is None or message.thread_root is None:
            return False
        key = f"{bot_id}:{message.thread_root}"
        known = self._bot_threads.get(key)
        if known is not None:
            return known
        response = await self._call(
            "GET",
            f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/event/"
            f"{_segment(message.thread_root)}",
            token,
        )
        if not response.is_success:
            return False
        root = response.json()
        root_message = read_message(root)
        ours = root.get("sender") == account.user_id or (
            root_message is not None and names(root_message, account.user_id, account.display_name)
        )
        self._bot_threads.put(key, ours)
        return ours

    async def _on_invite(
        self,
        bot_id: str,
        token: str,
        base_url: str,
        account: _Account,
        room_id: str,
        invited: dict[str, Any],
    ) -> None:
        """Join a room the access policy admits its inviter to, and decline the rest.

        A failed join is logged and left: the invitation is not delivered again,
        and a stream that stopped over one room would answer none.
        """
        own = next(
            (
                event
                for event in (invited.get("invite_state") or {}).get("events") or []
                if event.get("type") == "m.room.member"
                and event.get("state_key") == account.user_id
            ),
            None,
        )
        if own is None or not isinstance(own.get("sender"), str):
            return
        content = own.get("content") if isinstance(own.get("content"), dict) else {}
        admitted = await self._invite_admitted(
            bot_id, own["sender"], room_id, direct=content.get("is_direct") is True
        )
        action = "join" if admitted else "leave"
        response = await self._call(
            "POST", f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/{action}", token, body={}
        )
        if not response.is_success:
            logger.warning(
                "matrix_invite_unanswered",
                extra={"bot_id": bot_id, "action": action, "status": response.status_code},
            )

    @staticmethod
    async def _invite_admitted(bot_id: str, inviter: str, room_id: str, *, direct: bool) -> bool:
        """Whether the bot's access policy would answer the inviter in that room.

        The same `_check_access` a message passes, so an invitation can bring the
        bot nowhere a message from the same person could not reach it. Linking is
        not asked here: a person with no linked account is answered in a room and
        offered the link in a direct chat, as on every other platform.
        """
        from app.db.session import get_db_context
        from app.repositories import channel_bot_repo
        from app.services.channels.router import ChannelMessageRouter

        async with get_db_context() as db:
            bot = await channel_bot_repo.get_for_inbound(db, UUID(bot_id))
        if bot is None or not bot.is_active:
            return False
        probe = IncomingMessage(
            platform=PLATFORM,
            bot_id=bot_id,
            platform_user_id=inviter,
            platform_chat_id=room_key(room_id),
            chat_type="private" if direct else "group",
            text="",
        )
        try:
            ChannelMessageRouter()._check_access(probe, bot)
        except AuthorizationError:
            return False
        return True

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """A homeserver has no outgoing webhook; the bot reads its `/sync` instead."""
        return False

    async def delete_webhook(self, bot_token: str) -> bool:
        return False

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """No webhook route accepts Matrix traffic, so nothing verifies as Matrix's."""
        return False

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """Normalise one room message the sync loop has already placed.

        `raw_payload` is the room, the event and the two facts only the homeserver
        could answer - whether the room is a direct chat, and whether the message
        is in a thread the bot was asked in - read by `_on_sync` before this runs,
        so the parser itself makes no request.
        """
        room_id, event = raw_payload.get("room_id"), raw_payload.get("event")
        account, base_url = self._accounts.get(bot_id), self._servers.get(bot_id)
        if (
            not isinstance(room_id, str)
            or not isinstance(event, dict)
            or account is None
            or base_url is None
        ):
            return None
        message = read_message(event)
        if message is None or message.sender == account.user_id:
            return None
        attachment = attachment_of(message, base_url)
        text = without_mention(message.text, account.user_id, account.display_name)
        if not text and attachment is None:
            return None
        direct = raw_payload.get("direct") is True
        return IncomingMessage(
            platform=PLATFORM,
            bot_id=bot_id,
            platform_user_id=message.sender,
            platform_chat_id=thread_key(
                room_key(room_id), thread_id=message.thread_root or "", message_id=message.event_id
            ),
            chat_type="private" if direct else "group",
            text=text,
            raw={"room_id": room_id, "event_id": message.event_id},
            platform_username=message.sender,
            message_id=message.event_id,
            attachments=[attachment] if attachment is not None else [],
            broadcast_mention=_room_mentioned(message),
            addressed=direct
            or names(message, account.user_id, account.display_name)
            or raw_payload.get("bot_thread") is True,
        )


def _room_mentioned(message: Message) -> bool:
    """Whether the message calls the whole room: `@room`, as the client marked it or wrote it."""
    if message.mentioned is not None:
        return message.room_mentioned
    return "@room" in mentionable_text(message.text)
