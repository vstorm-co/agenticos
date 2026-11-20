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
from collections.abc import AsyncIterator
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
from app.services.channels.identity_scope import canonical_matrix_server
from app.services.channels.matrix_protocol import (
    CLIENT_API,
    MEDIA_UPLOAD,
    RELATIONS_API,
    SYNC_FILTER,
    SYNC_TIMEOUT_MS,
    Message,
    attachment_of,
    audience_of,
    chunks,
    display_names,
    edit_content,
    encrypted_invitation,
    error_code,
    file_content,
    names,
    reaction_content,
    read_message,
    retry_after,
    room_key,
    room_of,
    server_fingerprint,
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

_ENCRYPTED_DECLINED = (
    "This bot cannot read end-to-end encrypted rooms yet. Invite it to a room without encryption."
)

_REJECTED_TOKEN = frozenset({"M_UNKNOWN_TOKEN", "M_MISSING_TOKEN", "M_USER_DEACTIVATED"})

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client the sync position is kept in, or withdraw it."""
    global _redis
    _redis = redis


def _since_key(bot_id: str, user_id: str, server_url: str) -> str:
    # Keyed on the account as well: a token for another account must not resume
    # from a position that was never its own.
    return f"channel:matrix:since:{bot_id}:{hashlib.sha256(f'{server_fingerprint(server_url)}:{user_id}'.encode()).hexdigest()}"


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
    audience_key: str
    ids: list[str]
    shown: list[str] = field(default_factory=list)


def _segment(value: str) -> str:
    """One path segment: room ids, event ids and user ids carry `!`, `$`, `@` and `:`."""
    return quote(value, safe="")


def _reply_key(base_url: str, token: str, event_id: str) -> str:
    # A configured homeserver controls its returned ids. It must not overwrite
    # another connection's cached room or private audience by reusing one.
    credential = hashlib.sha256(f"{base_url}\n{token}".encode()).hexdigest()
    return f"{credential}:{event_id}"


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
        # A reaction or a decided prompt is handed the token but not the homeserver,
        # and runs in a worker that never opened the bot's stream: read off the row.
        self._homeservers: dict[str, tuple[str, float]] = {}
        # The homeserver and token of the reply a chat is waiting for, so the
        # typing notice that follows it needs neither from the row.
        self._composing: Recent[tuple[str, str]] = Recent(_CACHE_SIZE)
        self._names: Recent[str] = Recent(_CACHE_SIZE)
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
        self,
        base_url: str,
        token: str,
        room_id: str,
        event_type: str,
        content: dict[str, Any],
        *,
        audience_key: str,
    ) -> str:
        """Send one event and return its id. The transaction id makes a retry idempotent."""
        await self._require_recipient(base_url, token, room_id, audience_key)
        if await self._encrypted(base_url, token, room_id):
            raise ChannelDirectoryUnsupported(_ENCRYPTED_DECLINED)
        response = await self._call(
            "PUT",
            f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/send/{event_type}/{uuid4().hex}",
            token,
            body=content,
        )
        response.raise_for_status()
        return str(response.json()["event_id"])

    async def _upload(
        self,
        base_url: str,
        token: str,
        room_id: str,
        item: OutgoingAttachment,
        *,
        audience_key: str,
    ) -> str:
        await self._require_recipient(base_url, token, room_id, audience_key)
        if await self._encrypted(base_url, token, room_id):
            raise ChannelDirectoryUnsupported(_ENCRYPTED_DECLINED)
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

    async def _homeserver(self, bot_id: str) -> str:
        """A bot's homeserver, for a call that is handed the token but not the address.

        Read from the bot's row, as Teams reads a conversation it has not seen, and
        kept for a minute: a worker that never opened the bot's stream was never
        told it, and an edit to the bot reaches every worker within that minute.

        Raises:
            ChannelNotConfigured: If the bot is gone, paused or has no homeserver.
        """
        if bot_id in self._servers:
            return self._servers[bot_id]
        cached = self._homeservers.get(bot_id)
        if cached is not None and time.monotonic() - cached[1] < _ACCESS_SECONDS:
            return cached[0]
        from app.db.session import get_db_context
        from app.repositories import channel_bot_repo

        async with get_db_context() as db:
            bot = await channel_bot_repo.get_for_inbound(db, UUID(bot_id))
        if bot is None or bot.platform != PLATFORM or not bot.api_base_url:
            raise ChannelNotConfigured(
                message="This Matrix bot has no homeserver URL", details={"bot_id": bot_id}
            )
        base_url = bot.api_base_url.rstrip("/")
        self._homeservers[bot_id] = (base_url, time.monotonic())
        return base_url

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
                    base_url,
                    bot_token,
                    room_id,
                    "m.room.message",
                    text_content(piece, root=root),
                    audience_key=key,
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
            uri = await self._upload(base_url, bot_token, room_id, item, audience_key=key)
            sent = await self._send(
                base_url,
                bot_token,
                room_id,
                "m.room.message",
                file_content(item.filename, item.mime_type, len(item.content), uri, root=root),
                audience_key=key,
            )
        return sent

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Post the message the answer will be written into, and return its id."""
        base_url = self._base(msg.api_base_url)
        key, root = split_thread(msg.platform_chat_id)
        room_id = room_of(key)
        shown = chunks(msg.text)[0] or "…"
        event_id = await self._send(
            base_url,
            bot_token,
            room_id,
            "m.room.message",
            text_content(shown, root=root),
            audience_key=key,
        )
        self._replies.put(
            _reply_key(base_url, bot_token, event_id),
            _Reply(
                room_id=room_id, root=root or None, audience_key=key, ids=[event_id], shown=[shown]
            ),
        )
        self._composing.put(msg.platform_chat_id, (base_url, bot_token))
        return event_id

    async def update_reply(self, bot_token: str, msg: OutgoingMessage, handle: str) -> None:
        """Rewrite the answer with `m.replace` edits, spilling past `MESSAGE_LIMIT`.

        Each message is edited only when its part changed, and a part the answer
        no longer reaches is redacted - an output guardrail can shorten the
        answer at the end.
        """
        base_url = self._base(msg.api_base_url)
        cache_key = _reply_key(base_url, bot_token, handle)
        reply = self._replies.get(cache_key)
        if reply is None:
            # Another worker opened it, or this one restarted.
            key, root = split_thread(msg.platform_chat_id)
            reply = _Reply(
                room_id=room_of(key), root=root or None, audience_key=key, ids=[handle], shown=[""]
            )
            self._replies.put(cache_key, reply)
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
                        audience_key=reply.audience_key,
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
                        audience_key=reply.audience_key,
                    )
                )
                reply.shown.append(piece)
        while len(reply.ids) > len(pieces):
            stale = reply.ids[-1]
            response = await self._call(
                "PUT",
                f"{base_url}{CLIENT_API}/rooms/{_segment(reply.room_id)}/redact/"
                f"{_segment(stale)}/{uuid4().hex}",
                bot_token,
                body={},
            )
            response.raise_for_status()
            reply.ids.pop()
            reply.shown.pop()

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
        base_url = await self._homeserver(press.bot_id)
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
        base_url = await self._homeserver(incoming.bot_id)
        await self._send(
            base_url,
            bot_token,
            room_of(channel_key(incoming.platform_chat_id)),
            "m.reaction",
            reaction_content(incoming.message_id, symbol),
            audience_key=channel_key(incoming.platform_chat_id),
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
            base_url,
            bot_token,
            room_id,
            "m.reaction",
            reaction_content(message_id, symbol),
            audience_key=channel_id,
        )

    async def typing(self, bot_id: str, msg: OutgoingMessage) -> None:
        """Say the bot is composing in the room, for up to thirty seconds.

        Only after this process opened the reply the chat is waiting for, whose
        homeserver and token it reuses; the router always opens it first. Never
        fatal, as the base contract says: the placeholder says the same thing more
        durably, so a failure is logged, not raised.
        """
        known = self._composing.get(msg.platform_chat_id)
        if known is None:
            return
        base_url, token = known
        try:
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
            follow_redirects=False,
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

    async def _encrypted(self, base_url: str, token: str, room_id: str) -> bool:
        """Read current state; a room may enable encryption during an agent run.

        Do not cache the refusal boundary: neither a sync filter nor a previous
        plaintext message proves the room still accepts plaintext replies.
        """
        response = await self._call(
            "GET",
            f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/state/m.room.encryption/",
            token,
        )
        if response.status_code == 404:
            return False
        if response.status_code == 403:
            raise ChannelDirectoryUnsupported("This bot is not in that Matrix room")
        response.raise_for_status()
        # Presence, not a recognized algorithm: even malformed encryption state
        # cannot establish that sending plaintext is safe.
        return True

    async def _require_recipient(
        self, base_url: str, token: str, room_id: str, audience_key: str
    ) -> None:
        """Keep a private turn's answer with its original recipient, even after a restart.

        A room can change membership while a run is queued or using private
        context. Recounting two members is insufficient if the original person
        left: both identities must still be the same before posting any bytes.
        """
        server, recipient = audience_of(audience_key)
        if server is not None and server != server_fingerprint(base_url):
            raise ChannelDirectoryUnsupported(
                "This Matrix conversation belongs to a different homeserver. Start a new conversation with the bot."
            )
        if recipient is None:
            return
        own = await self._account(base_url, token)
        joined = await self._joined(base_url, token, room_id)
        if len(joined) != 2 or set(joined) != {own.user_id, recipient}:
            raise ChannelDirectoryUnsupported(
                "This Matrix conversation no longer has its original private audience. "
                "Start a new conversation with the bot."
            )

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
        self._homeservers.pop(bot_id, None)
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
            since = await self._load_since(bot_id, account.user_id, base_url)
            while True:
                batch = await self._sync(base_url, bot_token, since)
                await self._on_sync(
                    bot_id, bot_token, base_url, account, batch, backlog=since is None, since=since
                )
                since = str(batch["next_batch"])
                await self._store_since(bot_id, account.user_id, since, base_url)
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
    async def _load_since(bot_id: str, user_id: str, server_url: str) -> str | None:
        return None if _redis is None else await _redis.get(_since_key(bot_id, user_id, server_url))

    @staticmethod
    async def _store_since(bot_id: str, user_id: str, since: str, server_url: str) -> None:
        if _redis is not None:
            await _redis.set(_since_key(bot_id, user_id, server_url), since, ttl=_SINCE_TTL_SECONDS)

    async def _on_sync(
        self,
        bot_id: str,
        token: str,
        base_url: str,
        account: _Account,
        batch: dict[str, Any],
        *,
        backlog: bool,
        since: str | None = None,
    ) -> None:
        """Handle one sync batch: invitations, departures, then each room's new messages.

        `backlog` is the account's first sync, whose timeline is history: the bot
        joins nothing late and answers none of it. Rooms are handled side by side,
        each in its own order, so one slow homeserver call holds up only its room;
        the batch ends when every room has, and only then is its position stored.
        """
        rooms = batch.get("rooms") or {}
        for room_id, invited in (rooms.get("invite") or {}).items():
            await self._on_invite(bot_id, token, base_url, account, room_id, invited)
        for room_id in rooms.get("leave") or {}:
            self._direct.pop(f"{bot_id}:{room_id}")
        async with asyncio.TaskGroup() as rooms_at_once:
            for room_id, joined in (rooms.get("join") or {}).items():
                rooms_at_once.create_task(
                    self._on_room(
                        bot_id,
                        token,
                        base_url,
                        account,
                        room_id,
                        joined,
                        backlog=backlog,
                        since=since,
                    )
                )

    async def _on_room(
        self,
        bot_id: str,
        token: str,
        base_url: str,
        account: _Account,
        room_id: str,
        joined: dict[str, Any],
        *,
        backlog: bool,
        since: str | None = None,
    ) -> None:
        """One room's part of a sync batch, its messages in the order they were sent."""
        from app.services.channels.ingress import admit_message

        timeline = joined.get("timeline") or {}
        events: list[dict[str, Any]] = timeline.get("events") or []
        state: list[dict[str, Any]] = (joined.get("state") or {}).get("events") or []
        for user, name in display_names([*state, *events]).items():
            self._names.put(f"{bot_id}:{room_id}|{user}", name)
        key = f"{bot_id}:{room_id}"
        # Cache group classifications only within this batch. Private rooms are
        # always rechecked: lazy state can omit a silent membership change.
        self._direct.pop(key)
        if backlog:
            return
        if await self._encrypted(base_url, token, room_id):
            return
        async for event in self._room_events(
            bot_id, token, base_url, room_id, timeline, since=since
        ):
            if event.get("type") != "m.room.message" or event.get("sender") == account.user_id:
                continue
            direct = await self._is_direct(bot_id, token, base_url, room_id)
            incoming = self.parse_incoming(
                {
                    "room_id": room_id,
                    "event": event,
                    "direct": direct,
                    "bot_thread": not direct
                    and await self._in_bot_thread(bot_id, token, base_url, account, room_id, event),
                    "display_name": self._names.get(f"{bot_id}:{room_id}|{event.get('sender')}"),
                },
                bot_id,
            )
            if incoming is not None:
                await admit_message(incoming)

    async def _room_events(
        self,
        bot_id: str,
        token: str,
        base_url: str,
        room_id: str,
        timeline: dict[str, Any],
        *,
        since: str | None,
    ) -> AsyncIterator[dict[str, Any]]:
        if timeline.get("limited"):
            async for event in self._gap(bot_id, token, base_url, room_id, timeline, since=since):
                yield event
        for event in timeline.get("events") or []:
            yield event

    async def _gap(
        self,
        bot_id: str,
        token: str,
        base_url: str,
        room_id: str,
        timeline: dict[str, Any],
        *,
        since: str | None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Read a limited sync's gap forward from the previous durable cursor.

        Both endpoints accept sync tokens. Forward pages preserve admission order
        while retaining only one page, including after a restart. An empty page
        may still have a continuation; only a missing end token finishes it.
        """
        stop = timeline.get("prev_batch")
        if since is None or not isinstance(stop, str):
            logger.warning("matrix_timeline_gap_skipped", extra={"bot_id": bot_id})
            return
        position = since
        while position != stop:
            response = await self._call(
                "GET",
                f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/messages",
                token,
                params={
                    "dir": "f",
                    "from": position,
                    "to": stop,
                    "limit": 50,
                    "filter": '{"types":["m.room.message"]}',
                },
            )
            response.raise_for_status()
            page = response.json()
            for event in page.get("chunk") or []:
                yield event
            following = page.get("end")
            if not isinstance(following, str):
                return
            if following == position:
                raise RuntimeError("Matrix history pagination did not advance")
            position = following

    async def _is_direct(self, bot_id: str, token: str, base_url: str, room_id: str) -> bool:
        """Whether a room holds the bot and one other person, and nobody else.

        A room is the conservative reading: a group taken for a private chat would
        read the speaker's private memory into an answer the room sees (#1470), so
        a room whose members cannot be counted is a room.
        """
        key = f"{bot_id}:{room_id}"
        known = self._direct.get(key)
        if known is False:
            return False
        try:
            direct = len(await self._joined(base_url, token, room_id)) == 2
        except httpx.HTTPError, ChannelDirectoryUnsupported:
            logger.warning("matrix_members_unread", extra={"bot_id": bot_id}, exc_info=True)
            return False
        # Lazy membership state can omit a silent third joiner. Revalidate every
        # private classification; retaining only a group result is conservative.
        if not direct:
            self._direct.put(key, False)
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

        An encrypted room is declined with a reason the inviter's client shows: the
        bot would join and then read nothing there, which looks like a broken bot.
        A failed join is logged and left: the invitation is not delivered again,
        and a stream that stopped over one room would answer none.
        """
        from app.services.channels.ingress import invite_admitted

        stripped: list[dict[str, Any]] = (invited.get("invite_state") or {}).get("events") or []
        own = next(
            (
                event
                for event in stripped
                if event.get("type") == "m.room.member"
                and event.get("state_key") == account.user_id
            ),
            None,
        )
        if own is None or not isinstance(own.get("sender"), str):
            return
        content = own.get("content")
        direct = isinstance(content, dict) and content.get("is_direct") is True
        body: dict[str, str] = {}
        if encrypted_invitation(stripped):
            action, body["reason"] = "leave", _ENCRYPTED_DECLINED
        elif await invite_admitted(
            bot_id, own["sender"], room_key(room_id), direct=direct, server_url=base_url
        ):
            action = "join"
        else:
            action = "leave"
        response = await self._call(
            "POST", f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/{action}", token, body=body
        )
        # Stripped invitation state may omit encryption. Only joined-room state
        # can establish it, so leave an encrypted room immediately after joining.
        if (
            response.is_success
            and action == "join"
            and await self._encrypted(base_url, token, room_id)
        ):
            action = "leave"
            response = await self._call(
                "POST",
                f"{base_url}{CLIENT_API}/rooms/{_segment(room_id)}/leave",
                token,
                body={"reason": _ENCRYPTED_DECLINED},
            )
        if not response.is_success:
            logger.warning(
                "matrix_invite_unanswered",
                extra={"bot_id": bot_id, "action": action, "status": response.status_code},
            )

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
                room_key(
                    room_id,
                    server_url=base_url,
                    private_recipient=message.sender if direct else None,
                ),
                thread_id=message.thread_root or "",
                message_id=message.event_id,
            ),
            chat_type="private" if direct else "group",
            text=text,
            raw={
                "room_id": room_id,
                "event_id": message.event_id,
                "server_url": canonical_matrix_server(base_url),
            },
            platform_username=message.sender,
            platform_display_name=raw_payload.get("display_name")
            if isinstance(raw_payload.get("display_name"), str)
            else None,
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
