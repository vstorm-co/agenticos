"""Discord channel adapter (#2079).

Discord's API spoken directly - its Gateway over `websockets`, its REST API over
`httpx` - rather than through a library, the way the Mattermost adapter is: the
part of Discord a bot needs is small, and a library would bring its own event
loop, cache and reconnect logic to sit beside the ones this package already has.

**Gateway only.** Everything arrives over the bot's one Gateway connection,
slash commands and button presses included, so a deployment needs no public
address for Discord - the same bargain as Slack's Socket Mode. One connection
per bot across every worker, held by the stream lease. A bot in more than 2,500
servers needs sharding, which this does not do; Discord closes the connection
with 4011 and the bot's row says so.

**Conversations.** A message that mentions the bot in a server channel opens a
thread on that message, and the thread is the conversation; replying in it, or
anywhere in a thread the bot opened, continues it. A direct message is one
conversation, which `/new` starts over. `/ask` posts the question and threads
the answer under it, and *Apps → Ask the agent* on a message asks about that
message.

**What is posted is model output**, so nothing the bot posts may ping anybody
(`NO_MENTIONS`), and an answer is only ever written by editing the message the
router opened - never streamed raw - so a guardrail's redaction holds here as
everywhere (#1900).
"""

import asyncio
import contextlib
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
import logfire
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.agents.capabilities.channel_tools import ChannelPost
from app.core.background import spawn
from app.services.channels import connection_state
from app.services.channels.base import (
    CHANNEL_COMMANDS,
    ChannelAdapter,
    FeedbackComment,
    IncomingAttachment,
    IncomingMessage,
    IncomingPress,
    OutgoingMessage,
    PromptMessage,
    feedback_value,
    read_feedback,
    split_thread,
    supervise_stream,
    thread_key,
)
from app.services.channels.discord_protocol import (
    API_BASE,
    ASK,
    ASK_ABOUT,
    DM,
    GATEWAY_QUERY,
    MESSAGE_LIMIT,
    NO_MENTIONS,
    PRIVATE_THREAD,
    PUBLIC_BOT,
    THREAD_TYPES,
    Recent,
    attachment_type,
    can_view,
    chunks,
    close_refusal,
    commands,
    comment_form,
    components,
    identify,
    interaction_user,
    pressed_value,
    read_comment,
    resume,
    session_lost,
    thread_name,
    without_mention,
)
from app.services.channels.exceptions import ChannelNotConfigured
from app.worker.background.channel import (
    process_channel_event,
    process_channel_press,
    process_feedback_comment,
    refusal_before_publishing,
)

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 20.0
_RATE_LIMIT_RETRIES = 2
_RATE_LIMIT_CEILING = 10.0
_CACHE_SIZE = 10_000
# A close code of our own: 1000 and 1001 end the session for good, anything else
# leaves it resumable, which is what a reconnect we start wants.
_RESUMABLE_CLOSE = 4000
_CDN_HOSTS = frozenset({"cdn.discordapp.com", "media.discordapp.net"})
_ROUTED_COMMANDS = frozenset(name for name, _ in CHANNEL_COMMANDS)
_MESSAGE_TYPES = frozenset({0, 19})
"""A message somebody typed (0) or a reply (19); joins, pins and the rest are not."""
_REGISTER_BACKOFF = (5.0, 30.0, 120.0, 600.0)
NEW_OUTSIDE_THREAD: dict[str, Any] = {
    "type": 4,
    "data": {
        "content": "Every mention in this channel already starts a new conversation, in a "
        "thread of its own. Run /new inside a thread to start that one over.",
        "flags": 64,
    },
}
"""The answer to `/new` in a server channel, where there is nothing to start over."""
"""Seconds between attempts to register the commands after the first fails."""


@dataclass(frozen=True)
class _Channel:
    """What the adapter needs to know about a channel: whether it is a thread, and whose."""

    kind: int
    parent_id: str | None = None
    owner_id: str | None = None


@dataclass
class _Session:
    """A Gateway session, kept across connections so a drop can be resumed."""

    session_id: str | None = None
    resume_url: str | None = None
    seq: int | None = None
    acked: bool = True
    guilds: set[str] = field(default_factory=set)
    """The servers the bot was in when it identified, and those checked since."""
    refusal: str | None = None
    """Why the connection was closed from this side and must not be reopened."""
    unchecked: set[str] = field(default_factory=set)
    """Servers added since identifying whose public-bot check has not answered.

    Nothing they send is read until it does."""


@dataclass
class _Reply:
    """An answer being written, which may run past one message."""

    channel_id: str
    ids: list[str]
    shown: list[str] = field(default_factory=list)
    reference: str | None = None
    """The question each message replies to, where the bot could not open a thread."""


def _channel_of(payload: dict[str, Any]) -> _Channel:
    return _Channel(
        kind=int(payload.get("type") or 0),
        parent_id=payload.get("parent_id"),
        owner_id=payload.get("owner_id"),
    )


class DiscordAdapter(ChannelAdapter):
    """Discord, over its Gateway and REST API v10."""

    platform: str = "discord"

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        self._socket_tasks: dict[str, asyncio.Task[None]] = {}
        self._sessions: dict[str, _Session] = {}
        self._tokens: dict[str, str] = {}
        # Which account and which application each bot is, from its READY.
        self._own_ids: dict[str, str] = {}
        self._app_ids: dict[str, str] = {}
        self._registered: set[str] = set()
        # Each bot's managed roles, one per server it is in: mentioning the role
        # addresses the bot as mentioning the bot does.
        self._own_roles: dict[str, set[str]] = {}
        # Channel ids are global, so one cache serves every bot.
        self._channels: Recent[_Channel] = Recent(_CACHE_SIZE)
        self._threads: Recent[bool] = Recent(_CACHE_SIZE)
        self._unthreaded: Recent[bool] = Recent(_CACHE_SIZE)
        self._thread_names: Recent[str] = Recent(_CACHE_SIZE)
        self._replies: Recent[_Reply] = Recent(_CACHE_SIZE)
        # A command's reply is written into the interaction's own deferred
        # response, keyed on the interaction id the message carries.
        self._interactions: Recent[tuple[str, str]] = Recent(_CACHE_SIZE)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(
        self,
        method: str,
        path: str,
        bot_token: str | None,
        *,
        body: dict[str, Any] | list[dict[str, Any]] | None = None,
        files: list[tuple[str, bytes, str]] | None = None,
    ) -> httpx.Response:
        """One REST call, waiting out Discord's rate limit a couple of times.

        A streamed answer edits once a second, which Discord's per-channel limit
        allows but a busy channel can tip over; the 429 says how long to wait.
        Interaction callbacks and webhooks authenticate by their own token and
        are sent without the bot's, and are not traced.
        """
        headers = {"Authorization": f"Bot {bot_token}"} if bot_token else {}
        attempt = 0
        # Without the bot's token the credential is the interaction's, and it is
        # in the URL: kept out of tracing, which exports a request's URL whole.
        tracing = (
            logfire.suppress_instrumentation() if bot_token is None else contextlib.nullcontext()
        )
        with tracing:
            while True:
                if files:
                    response = await self._http.request(
                        method,
                        f"{API_BASE}{path}",
                        headers=headers,
                        data={"payload_json": json.dumps(body or {})},
                        files=[
                            (f"files[{index}]", (name, content, mime))
                            for index, (name, content, mime) in enumerate(files)
                        ],
                    )
                else:
                    response = await self._http.request(
                        method, f"{API_BASE}{path}", headers=headers, json=body
                    )
                if response.status_code != 429 or attempt == _RATE_LIMIT_RETRIES:
                    return response
                attempt += 1
                wait = float(response.json().get("retry_after", 1.0))
                await asyncio.sleep(min(wait, _RATE_LIMIT_CEILING))

    async def _destination(self, bot_token: str, chat_key: str) -> tuple[str, str | None]:
        """Where a message for `chat_key` goes: a channel, and a message to reply to.

        The key's thread half is the thread's id. A thread opened on a message
        has that message's id, so a key minted before the thread exists is
        already the thread's - and the thread is opened here, on the first post
        into it. A channel where the bot may not open threads gets its answer
        as a reply to the message instead.

        A thread this process has not seen - after a restart, on another
        worker, or one started without a message - is asked about first. It
        has no message to open a thread on, and falling back to a reply would
        put its answer in the channel around it.
        """
        channel, thread = split_thread(chat_key)
        if not thread or thread in self._threads:
            return thread or channel, None
        if chat_key in self._unthreaded:
            return channel, thread
        await self._learn_channel(bot_token, thread)
        known = self._channels.get(thread)
        if known is not None and known.kind in THREAD_TYPES:
            self._threads.put(thread, True)
            return thread, None
        response = await self._call(
            "POST",
            f"/channels/{channel}/messages/{thread}/threads",
            bot_token,
            body={
                "name": self._thread_names.get(chat_key) or "Conversation",
                "auto_archive_duration": 1440,
            },
        )
        # 160004: a thread was already opened on this message - by another
        # worker, or before a restart emptied this cache.
        if response.is_success or _error_code(response) == 160004:
            self._threads.put(thread, True)
            return thread, None
        logger.warning(
            "discord_thread_not_opened",
            extra={"status": response.status_code, "code": _error_code(response)},
        )
        self._unthreaded.put(chat_key, True)
        return channel, thread

    async def _post(
        self,
        bot_token: str,
        channel_id: str,
        content: str,
        *,
        reference: str | None = None,
        files: list[tuple[str, bytes, str]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "content": content,
            "allowed_mentions": NO_MENTIONS,
            **(extra or {}),
        }
        if reference:
            body["message_reference"] = {"message_id": reference, "fail_if_not_exists": False}
        response = await self._call(
            "POST", f"/channels/{channel_id}/messages", bot_token, body=body, files=files
        )
        response.raise_for_status()
        return str(response.json()["id"])

    async def _edit(
        self, bot_token: str, channel_id: str, message_id: str, body: dict[str, Any]
    ) -> None:
        response = await self._call(
            "PATCH",
            f"/channels/{channel_id}/messages/{message_id}",
            bot_token,
            body={"allowed_mentions": NO_MENTIONS, **body},
        )
        response.raise_for_status()

    async def _answer_interaction(
        self, interaction_id: str, token: str, body: dict[str, Any]
    ) -> None:
        """Respond to an interaction - within three seconds, or Discord shows it failed."""
        response = await self._call(
            "POST", f"/interactions/{interaction_id}/{token}/callback", None, body=body
        )
        response.raise_for_status()

    async def _reply_to_interaction(self, interaction_id: str, text: str) -> bool:
        """Write `text` into a command's deferred response, if the message answers one."""
        found = self._interactions.get(interaction_id)
        if found is None:
            return False
        app_id, token = found
        pieces = chunks(text)
        response = await self._call(
            "PATCH",
            f"/webhooks/{app_id}/{token}/messages/@original",
            None,
            body={"content": pieces[0], "allowed_mentions": NO_MENTIONS},
        )
        response.raise_for_status()
        for piece in pieces[1:]:
            followed = await self._call(
                "POST",
                f"/webhooks/{app_id}/{token}",
                None,
                body={"content": piece, "flags": 64, "allowed_mentions": NO_MENTIONS},
            )
            followed.raise_for_status()
        return True

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Post a reply, in as many messages as it takes, files on the last."""
        if msg.reply_to_message_id and await self._reply_to_interaction(
            msg.reply_to_message_id, msg.text
        ):
            return
        channel_id, reference = await self._destination(bot_token, msg.platform_chat_id)
        files: list[tuple[str, bytes, str]] = []
        if msg.image_png is not None:
            files.append((msg.image_filename, msg.image_png, "image/png"))
        files.extend((item.filename, item.content, item.mime_type) for item in msg.attachments)
        pieces = chunks(msg.text)
        for index, piece in enumerate(pieces):
            last = index == len(pieces) - 1
            if not piece and not (last and files):
                continue
            await self._post(
                bot_token,
                channel_id,
                piece,
                # Every message, not the first alone: where no thread could be
                # opened, a reply to any of them must find the question.
                reference=reference,
                files=files if last and files else None,
            )

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Post the message the answer will be written into, and return its id."""
        if msg.reply_to_message_id:
            # *Ask the agent* answers in a thread from here on, files included;
            # only what refused it beforehand went to the asker alone.
            self._interactions.pop(msg.reply_to_message_id)
        channel_id, reference = await self._destination(bot_token, msg.platform_chat_id)
        shown = chunks(msg.text)[0] or "…"
        message_id = await self._post(bot_token, channel_id, shown, reference=reference)
        self._replies.put(
            message_id,
            _Reply(channel_id=channel_id, ids=[message_id], shown=[shown], reference=reference),
        )
        return message_id

    async def update_reply(self, bot_token: str, msg: OutgoingMessage, handle: str) -> None:
        """Rewrite the answer, spilling past 2,000 characters into messages after it.

        Each message is edited only when its part changed, and a part the answer
        no longer reaches is deleted - an output guardrail can shorten the
        answer at the end.
        """
        reply = self._replies.get(handle)
        if reply is None:
            # Another worker opened it, or this one restarted.
            channel_id, reference = await self._destination(bot_token, msg.platform_chat_id)
            reply = _Reply(channel_id=channel_id, ids=[handle], shown=[""], reference=reference)
            self._replies.put(handle, reply)
        pieces = [piece or "…" for piece in chunks(msg.text)]
        for index, piece in enumerate(pieces):
            if index < len(reply.ids):
                if reply.shown[index] != piece:
                    await self._edit(
                        bot_token, reply.channel_id, reply.ids[index], {"content": piece}
                    )
                    reply.shown[index] = piece
            else:
                reply.ids.append(
                    await self._post(bot_token, reply.channel_id, piece, reference=reply.reference)
                )
                reply.shown.append(piece)
        while len(reply.ids) > len(pieces):
            stale = reply.ids.pop()
            reply.shown.pop()
            response = await self._call(
                "DELETE", f"/channels/{reply.channel_id}/messages/{stale}", bot_token
            )
            if response.status_code != 404:
                response.raise_for_status()

    async def typing(self, bot_id: str, msg: OutgoingMessage) -> None:
        """Show the bot composing where the answer will appear, never opening a thread for it."""
        token = self._tokens.get(bot_id)
        if token is None:
            return
        channel, thread = split_thread(msg.platform_chat_id)
        target = thread if thread and thread in self._threads else channel
        with contextlib.suppress(Exception):
            await self._call("POST", f"/channels/{target}/typing", token)

    async def send_prompt(self, bot_token: str, prompt: PromptMessage) -> None:
        """An approval or a question, with a button per choice - or selects, past 25."""
        channel_id, reference = await self._destination(bot_token, prompt.platform_chat_id)
        pieces = chunks(prompt.text)
        for piece in pieces[:-1]:
            await self._post(bot_token, channel_id, piece, reference=reference)
            reference = None
        await self._post(
            bot_token,
            channel_id,
            pieces[-1],
            reference=reference,
            extra={"components": components(prompt.choices)},
        )

    async def acknowledge(self, bot_token: str, press: IncomingPress) -> None:
        """Nothing to do: the press was acknowledged the moment it arrived.

        Discord fails an interaction that is not answered in three seconds, and
        the work behind a press can take longer, so the Gateway handler answers
        it before routing.
        """

    async def settle_prompt(self, bot_token: str, press: IncomingPress, text: str) -> None:
        """Take the buttons off the pressed message, leaving what was asked and chosen."""
        if press.message_id is None:
            return
        chosen = f"**{text}**"[:MESSAGE_LIMIT]
        # The question is cut to leave room for the choice, never the other way
        # round: a prompt that fills the message would otherwise lose the one
        # line that says what was decided.
        room = MESSAGE_LIMIT - len(chosen) - 1
        shown = f"{press.prompt_text[: max(room, 0)]}\n{chosen}" if press.prompt_text else chosen
        await self._edit(
            bot_token,
            press.platform_chat_id,
            press.message_id,
            {"content": shown[:MESSAGE_LIMIT], "components": []},
        )

    async def offer_feedback(
        self, bot_token: str, msg: OutgoingMessage, handle: str, run_id: str, *, bot_id: str
    ) -> None:
        """Thumbs under the answer's last message."""
        reply = self._replies.get(handle)
        channel_id = (
            reply.channel_id
            if reply is not None
            else (await self._destination(bot_token, msg.platform_chat_id))[0]
        )
        last = reply.ids[-1] if reply is not None else handle
        await self._edit(
            bot_token,
            channel_id,
            last,
            {
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 2,
                                "style": 2,
                                "emoji": {"name": "👍"},
                                "custom_id": feedback_value(run_id, helpful=True),
                            },
                            {
                                "type": 2,
                                "style": 2,
                                "emoji": {"name": "👎"},
                                "custom_id": feedback_value(run_id, helpful=False),
                            },
                        ],
                    }
                ]
            },
        )

    async def settle_feedback(self, bot_token: str, press: IncomingPress, helpful: bool) -> None:
        """Say privately that a thumbs-up was taken; a thumbs-down already opened the form.

        The buttons stay, so everybody else in the thread can rate too.
        """
        app_id = self._app_ids.get(press.bot_id)
        if not helpful or app_id is None or press.ack_id is None:
            return
        response = await self._call(
            "POST",
            f"/webhooks/{app_id}/{press.ack_id}",
            None,
            body={"content": "Thanks for rating this answer.", "flags": 64},
        )
        response.raise_for_status()

    async def download_attachment(self, bot_token: str, attachment: IncomingAttachment) -> bytes:
        """Fetch a file from Discord's CDN, which serves it on the signed URL the message carried."""
        if urlparse(attachment.handle).hostname not in _CDN_HOSTS:
            raise ValueError("Not a Discord attachment URL")
        # The signed query is the credential, and tracing exports a request's URL
        # whole: kept out, as the interaction callbacks are.
        with logfire.suppress_instrumentation():
            response = await self._http.get(attachment.handle)
        response.raise_for_status()
        return response.content

    async def is_channel_member(
        self, bot_token: str, channel_id: str, platform_user_id: str, *, api_base_url: str | None
    ) -> bool:
        """Whether this account can still see the channel - which is what membership is on Discord.

        A server channel has no member list; anybody whose roles let them view it
        is in it. So the answer is computed from the server's roles, the
        member's and the channel's overwrites. A thread is judged by its parent,
        and a private thread also by its own members: it is invite-only, so
        seeing the parent is not being in it.
        """
        found = await self._call("GET", f"/channels/{channel_id}", bot_token)
        if found.status_code in (403, 404):
            return False
        found.raise_for_status()
        channel = found.json()
        if channel.get("type") == DM:
            return any(
                user.get("id") == platform_user_id for user in channel.get("recipients") or []
            )
        if channel.get("type") in THREAD_TYPES and channel.get("parent_id"):
            if channel.get("type") == PRIVATE_THREAD:
                joined = await self._call(
                    "GET", f"/channels/{channel_id}/thread-members/{platform_user_id}", bot_token
                )
                if joined.status_code == 404:
                    return False
                joined.raise_for_status()
            return await self.is_channel_member(
                bot_token, channel["parent_id"], platform_user_id, api_base_url=api_base_url
            )
        guild_id = str(channel.get("guild_id") or "")
        guild = await self._call("GET", f"/guilds/{guild_id}", bot_token)
        guild.raise_for_status()
        member = await self._call(
            "GET", f"/guilds/{guild_id}/members/{platform_user_id}", bot_token
        )
        if member.status_code == 404:
            return False
        member.raise_for_status()
        return can_view(
            user_id=platform_user_id,
            guild_id=guild_id,
            owner_id=str(guild.json().get("owner_id") or ""),
            roles={
                str(role["id"]): int(role["permissions"])
                for role in guild.json().get("roles") or []
            },
            member_roles=[str(role) for role in member.json().get("roles") or []],
            overwrites=channel.get("permission_overwrites") or [],
        )

    async def _messages(self, bot_token: str, channel_id: str, limit: int) -> list[dict[str, Any]]:
        """The last `limit` messages of one channel or thread, oldest first, without system ones.

        Discord answers newest first and 100 at most. A system message - somebody
        joined, a thread was renamed, a pin was added - is not what was said, so
        only a plain message (0) and a reply (19) are kept.
        """
        response = await self._call(
            "GET", f"/channels/{channel_id}/messages?limit={min(max(limit, 1), 100)}", bot_token
        )
        response.raise_for_status()
        return [
            message
            for message in reversed(response.json())
            if message.get("type") in _SPOKEN_MESSAGE_TYPES
        ]

    async def channel_history(
        self,
        bot_token: str,
        channel_id: str,
        *,
        api_base_url: str | None,
        limit: int,
        thread_id: str | None = None,
    ) -> list[ChannelPost]:
        """The recent transcript, newest last: the thread when the agent is in one.

        A Discord thread is a channel of its own, so reading it is the same call as
        reading the channel it hangs from - with the thread's id. Asked for the
        parent while answering in a thread, "summarise what we decided above"
        summarised the rest of the room.
        """
        return [
            ChannelPost(
                author=str(
                    (message.get("author") or {}).get("global_name")
                    or (message.get("author") or {}).get("username")
                    or "unknown"
                ),
                text=str(message.get("content") or ""),
                posted_at=_posted_at(message.get("timestamp")),
                post_id=str(message["id"]),
                author_id=(
                    str((message.get("author") or {}).get("id"))
                    if (message.get("author") or {}).get("id")
                    else None
                ),
            )
            for message in await self._messages(bot_token, thread_id or channel_id, limit)
        ]

    async def thread_attachments(
        self,
        bot_token: str,
        channel_id: str,
        *,
        thread_id: str,
        api_base_url: str | None,
        limit: int,
    ) -> list[IncomingAttachment]:
        """The files on a thread's earlier messages, oldest first, as handles.

        What a bot posted itself - a chart it drew, a file it returned - is left
        out, so the agent is not handed its own output to answer about. The URLs
        are the signed ones Discord just returned, which `download_attachment`
        fetches like those of a live message.
        """
        found: list[IncomingAttachment] = []
        for message in await self._messages(bot_token, thread_id, limit):
            if (message.get("author") or {}).get("bot"):
                continue
            author = (message.get("author") or {}).get("id")
            found.extend(_attachments(message, by=str(author) if author else None))
        return found

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """Open the bot's Gateway connection."""
        existing = self._socket_tasks.get(bot_id)
        if existing is not None and not existing.done():
            logger.info("Discord Gateway already running for bot %s", bot_id)
            return
        self._tokens[bot_id] = bot_token
        self._socket_tasks[bot_id] = asyncio.create_task(
            self._supervise(bot_id, bot_token), name=f"discord_gateway_{bot_id}"
        )
        logger.info("Started Discord Gateway for bot %s", bot_id)

    async def stop_polling(self, bot_id: str) -> None:
        task = self._socket_tasks.pop(bot_id, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # A token may have changed; the next connection identifies afresh.
        self._sessions.pop(bot_id, None)
        self._own_roles.pop(bot_id, None)
        logger.info("Stopped Discord Gateway for bot %s", bot_id)

    async def _supervise(self, bot_id: str, bot_token: str) -> None:
        await supervise_stream(
            bot_id,
            platform="Discord Gateway",
            session=lambda: self._run_stream(bot_id, bot_token),
            failing=(
                "The Discord Gateway connection keeps dropping. Check that the "
                "deployment can reach discord.com and the bot token is still valid."
            ),
        )

    async def _gateway_url(self, bot_token: str, bot_id: str) -> str:
        """Where to connect, asked with the token - so a rejected token or a public bot stops here."""
        response = await self._call("GET", "/gateway/bot", bot_token)
        if response.status_code == 401:
            raise ChannelNotConfigured(
                message=close_refusal(4004) or "Discord rejected the bot token.",
                details={"bot_id": bot_id},
            )
        response.raise_for_status()
        if await self._is_public(bot_token):
            raise ChannelNotConfigured(message=PUBLIC_BOT, details={"bot_id": bot_id})
        return str(response.json()["url"])

    async def _check_public(self, guild: str, bot_token: str, session: _Session) -> None:
        """Clear a newly added server for reading, or stop the connection when the bot is public."""
        try:
            public = await self._is_public(bot_token)
        except Exception:
            # Unknown is not public: the server stays unread until a later
            # event of it is checked, and the connection is not torn down for a
            # failed question.
            logger.warning("discord_public_check_failed", exc_info=True)
            session.unchecked.discard(guild)
            return
        session.unchecked.discard(guild)
        if public:
            session.refusal = PUBLIC_BOT

    async def _is_public(self, bot_token: str) -> bool:
        """Whether anyone may add this bot to their server - see :data:`PUBLIC_BOT`."""
        application = await self._call("GET", "/applications/@me", bot_token)
        application.raise_for_status()
        return bool(application.json().get("bot_public"))

    async def _run_stream(self, bot_id: str, bot_token: str) -> None:
        """One Gateway connection: hello, identify or resume, then events until it closes."""
        session = self._sessions.setdefault(bot_id, _Session())
        url = (
            session.resume_url
            if session.session_id and session.resume_url
            else await self._gateway_url(bot_token, bot_id)
        )
        async with connect(f"{url.rstrip('/')}/{GATEWAY_QUERY}", max_size=None) as socket:
            hello = json.loads(await socket.recv())
            interval = float(hello["d"]["heartbeat_interval"]) / 1000
            if session.session_id:
                await socket.send(json.dumps(resume(bot_token, session.session_id, session.seq)))
            else:
                await socket.send(json.dumps(identify(bot_token)))
            session.acked = True
            beat = asyncio.create_task(self._heartbeat(socket, interval, session))
            alive = asyncio.create_task(connection_state.heartbeat(bot_id))
            try:
                async for frame in socket:
                    await self._on_frame(frame, socket, bot_id, bot_token, session)
            except ConnectionClosed:
                # Any close but 1000 and 1001 raises here, Discord's own codes
                # included; what the code means is read below.
                pass
            finally:
                for task in (beat, alive):
                    task.cancel()
                    # A beat sent as the socket closed has already failed with
                    # the close; it must not stand in for the code read below.
                    with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                        await task
            code = socket.close_code
        if session.refusal is not None:
            self._sessions.pop(bot_id, None)
            raise ChannelNotConfigured(message=session.refusal, details={"bot_id": bot_id})
        refusal = close_refusal(code)
        if refusal is not None:
            self._sessions.pop(bot_id, None)
            raise ChannelNotConfigured(message=refusal, details={"bot_id": bot_id, "code": code})
        if session_lost(code):
            self._sessions.pop(bot_id, None)

    async def _heartbeat(self, socket: Any, interval: float, session: _Session) -> None:
        """Beat on Discord's interval; a beat never acknowledged means the connection is dead.

        The first beat is jittered, as Discord asks, so a deployment restarting
        a hundred bots does not beat them all at once.
        """
        await asyncio.sleep(interval * random.random())  # noqa: S311 - jitter, not a secret
        while True:
            if session.refusal is not None:
                # Found out off the receive loop, which only looks when an event
                # arrives: a quiet bot would otherwise stay connected.
                await socket.close(1000, "refused")
                return
            if not session.acked:
                await socket.close(_RESUMABLE_CLOSE, "heartbeat not acknowledged")
                return
            session.acked = False
            await socket.send(json.dumps({"op": 1, "d": session.seq}))
            await asyncio.sleep(interval)

    async def _on_frame(
        self, frame: str | bytes, socket: Any, bot_id: str, bot_token: str, session: _Session
    ) -> None:
        """Handle one Gateway payload. A malformed one is skipped, never fatal."""
        try:
            payload = json.loads(frame)
        except json.JSONDecodeError, TypeError:
            return
        op = payload.get("op")
        if op == 11:
            session.acked = True
        elif op == 1:
            await socket.send(json.dumps({"op": 1, "d": session.seq}))
        elif op == 7:
            await socket.close(_RESUMABLE_CLOSE, "reconnect requested")
        elif op == 9:
            if not payload.get("d"):
                session.session_id = None
                session.seq = None
            await socket.close(_RESUMABLE_CLOSE, "invalid session")
        elif op == 0:
            if payload.get("s") is not None:
                session.seq = payload["s"]
            try:
                await self._on_dispatch(
                    str(payload.get("t")), payload.get("d") or {}, bot_id, bot_token, session
                )
            except Exception:
                logger.exception("discord_event_failed", extra={"event": str(payload.get("t"))})
            if session.refusal is not None:
                await socket.close(1000, "refused")

    async def _on_dispatch(
        self, event: str, data: dict[str, Any], bot_id: str, bot_token: str, session: _Session
    ) -> None:
        if event == "READY":
            session.session_id = data.get("session_id")
            session.resume_url = data.get("resume_gateway_url")
            self._own_ids[bot_id] = str((data.get("user") or {}).get("id") or "")
            self._app_ids[bot_id] = str((data.get("application") or {}).get("id") or "")
            session.guilds = {str(guild.get("id")) for guild in data.get("guilds") or []}
            # Every server announces itself again after READY, and the roles are
            # read from those: a replaced token must not keep the old bot's.
            self._own_roles[bot_id] = set()
            await connection_state.record_up(bot_id)
            spawn(self._register_commands(bot_id, bot_token), name=f"discord-commands:{bot_id}")
        elif event == "RESUMED":
            await connection_state.record_up(bot_id)
        elif event == "GUILD_CREATE":
            for channel in [*(data.get("channels") or []), *(data.get("threads") or [])]:
                self._channels.put(str(channel["id"]), _channel_of(channel))
            # A server the bot was added to since it identified, which the check
            # before connecting never saw - and a resumed connection never repeats
            # it. Asked off the receive loop, so a slow answer cannot hold later
            # interactions from every other server past Discord's three seconds;
            # what that server sends is dropped until it comes.
            own = self._own_ids.get(bot_id)
            self._own_roles.setdefault(bot_id, set()).update(
                str(role["id"])
                for role in data.get("roles") or []
                if own and (role.get("tags") or {}).get("bot_id") == own
            )
            guild = str(data.get("id") or "")
            if guild not in session.guilds:
                session.guilds.add(guild)
                session.unchecked.add(guild)
                spawn(
                    self._check_public(guild, bot_token, session),
                    name=f"discord-public-check:{bot_id}",
                )
        elif event in ("CHANNEL_CREATE", "CHANNEL_UPDATE", "THREAD_CREATE", "THREAD_UPDATE"):
            self._channels.put(str(data["id"]), _channel_of(data))
        elif event == "THREAD_LIST_SYNC":
            for channel in data.get("threads") or []:
                self._channels.put(str(channel["id"]), _channel_of(channel))
        # A message or an interaction may call Discord before it is routed, and
        # the next frame is not read until this returns: off the receive loop,
        # so one slow call cannot hold a later interaction past the three
        # seconds Discord gives to answer it.
        elif event in ("MESSAGE_CREATE", "INTERACTION_CREATE") and (
            str(data.get("guild_id") or "") in session.unchecked
        ):
            return
        elif event == "MESSAGE_CREATE":
            spawn(self._on_message(data, bot_id, bot_token), name=f"discord-message:{bot_id}")
        elif event == "INTERACTION_CREATE":
            spawn(self._on_interaction(data, bot_id), name=f"discord-interaction:{bot_id}")

    async def _on_message(self, data: dict[str, Any], bot_id: str, bot_token: str) -> None:
        if data.get("guild_id"):
            await self._learn_channel(bot_token, str(data.get("channel_id")))
        incoming = self.parse_incoming(data, bot_id)
        if incoming is not None:
            spawn(process_channel_event(incoming), name=f"discord-routed:{bot_id}")

    async def _learn_channel(self, bot_token: str, channel_id: str) -> None:
        """Look a channel up the first time a message names it, to know whether it is a thread."""
        if channel_id in self._channels:
            return
        response = await self._call("GET", f"/channels/{channel_id}", bot_token)
        if response.is_success:
            self._channels.put(channel_id, _channel_of(response.json()))

    async def _register_commands(self, bot_id: str, bot_token: str) -> None:
        """Put `/ask`, the channel commands and *Ask the agent* on the bot, once per process.

        A bulk overwrite, so a command removed here is removed from Discord too.
        Global commands take a while to show in every server; that is Discord's.
        Remembered per application rather than per bot, because a row whose
        token is replaced may now be a different application with none.

        A failed attempt is retried on :data:`_REGISTER_BACKOFF`: a dropped
        connection resumes rather than sending READY again, so waiting for the
        next READY could leave the bot without its commands for days.
        """
        app_id = self._app_ids.get(bot_id)
        if not app_id:
            return
        for delay in (0.0, *_REGISTER_BACKOFF):
            await asyncio.sleep(delay)
            if app_id in self._registered:
                return
            try:
                response = await self._call(
                    "PUT", f"/applications/{app_id}/commands", bot_token, body=commands()
                )
            except httpx.HTTPError:
                logger.warning("discord_commands_not_registered", exc_info=True)
                continue
            if response.is_success:
                self._registered.add(app_id)
                return
            logger.warning(
                "discord_commands_not_registered", extra={"status": response.status_code}
            )

    def _chat_key(self, channel_id: str, *, guild: bool, message_id: str | None) -> str:
        """The conversation a message in `channel_id` belongs to - see `thread_key`.

        A direct message is the chat itself. In a server, a thread is keyed on
        its parent and itself - a private thread on itself alone - and a message
        outside one on the message, where its thread will be opened.
        """
        if not guild:
            return channel_id
        channel = self._channels.get(channel_id)
        if channel is not None and channel.kind in THREAD_TYPES and channel.parent_id:
            self._threads.put(channel_id, True)
            # A private thread is invite-only, so it is keyed on itself, as channel
            # and as thread: its room memory and who may read it in the console are
            # then its members', not everybody's who can see the parent, and a bot
            # brought in partway still has a thread to read the earlier messages of.
            if channel.kind == PRIVATE_THREAD:
                return f"{channel_id}:{channel_id}"
            return f"{channel.parent_id}:{channel_id}"
        return thread_key(channel_id, thread_id="", message_id=message_id)

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """A Gateway `MESSAGE_CREATE`, or `None` for one the bot should not hear.

        Addressed when it mentions the bot, replies to one of its messages, or is
        in a thread the bot opened - that thread is a conversation with it.
        """
        author = raw_payload.get("author") or {}
        own = self._own_ids.get(bot_id)
        if (
            author.get("bot")
            or raw_payload.get("webhook_id")
            or (own and author.get("id") == own)
            or raw_payload.get("type") not in _MESSAGE_TYPES
        ):
            return None
        channel_id = str(raw_payload.get("channel_id") or "")
        guild = bool(raw_payload.get("guild_id"))
        text = raw_payload.get("content") or ""
        key = self._chat_key(
            channel_id, guild=guild, message_id=_conversation_root(raw_payload, own)
        )
        roles = self._own_roles.get(bot_id, set())
        addressed: bool | None = True
        if guild:
            if own is None:
                addressed = None
            else:
                replied = ((raw_payload.get("referenced_message") or {}).get("author") or {}).get(
                    "id"
                )
                channel = self._channels.get(channel_id)
                addressed = (
                    any(user.get("id") == own for user in raw_payload.get("mentions") or [])
                    or not roles.isdisjoint(raw_payload.get("mention_roles") or [])
                    or replied == own
                    or (channel is not None and channel.owner_id == own)
                )
            if ":" in key and key.endswith(f":{raw_payload.get('id')}"):
                self._thread_names.put(key, thread_name(text))
        if own:
            text = without_mention(text, own, roles)
        attachments = _attachments(raw_payload)
        if not text and not attachments:
            return None
        member = raw_payload.get("member") or {}
        return IncomingMessage(
            platform=self.platform,
            bot_id=bot_id,
            platform_user_id=str(author.get("id") or ""),
            platform_chat_id=key,
            chat_type="group" if guild else "private",
            text=text,
            raw=raw_payload,
            platform_username=author.get("username"),
            platform_display_name=member.get("nick") or author.get("global_name"),
            message_id=raw_payload.get("id"),
            # Set by Discord only when the sender's ping went out, so text that
            # merely reads "@everyone" from somebody without the permission is
            # not a broadcast here either.
            broadcast_mention=bool(raw_payload.get("mention_everyone")),
            addressed=addressed,
            attachments=attachments,
        )

    async def _on_interaction(self, data: dict[str, Any], bot_id: str) -> None:
        """A slash command, a message command, a pressed component or a submitted form."""
        kind = data.get("type")
        interaction_id = str(data.get("id") or "")
        token = str(data.get("token") or "")
        if kind == 2:
            await self._on_command(data, bot_id, interaction_id, token)
        elif kind == 3:
            await self._on_press(data, bot_id, interaction_id, token)
        elif kind == 5:
            parsed = read_comment(data.get("data") or {})
            if parsed is None:
                await self._answer_interaction(
                    interaction_id,
                    token,
                    {"type": 4, "data": {"content": "There was no comment to keep.", "flags": 64}},
                )
                return
            # Deferred: only saving it finds out whether it can be kept - an
            # unlinked account, a run that is gone - and the answer says which.
            await self._answer_interaction(
                interaction_id, token, {"type": 5, "data": {"flags": 64}}
            )
            run_id, text = parsed
            spawn(
                self._keep_comment(
                    self._app_id(data, bot_id),
                    token,
                    FeedbackComment(
                        platform=self.platform,
                        bot_id=bot_id,
                        platform_user_id=str(interaction_user(data).get("id") or ""),
                        run_id=run_id,
                        text=text,
                    ),
                ),
                name=f"discord-feedback:{bot_id}",
            )

    async def _keep_comment(self, app_id: str, token: str, comment: FeedbackComment) -> None:
        """Save a comment from the thumbs-down form, then tell its writer whether it was kept."""
        kept = await process_feedback_comment(comment)
        response = await self._call(
            "PATCH",
            f"/webhooks/{app_id}/{token}/messages/@original",
            None,
            body={
                "content": "Thanks - that goes to the agent's builders."
                if kept
                else "That comment could not be kept. If your Discord account is not linked "
                "yet, run /link and try again.",
                "allowed_mentions": NO_MENTIONS,
            },
        )
        response.raise_for_status()

    def _app_id(self, data: dict[str, Any], bot_id: str) -> str:
        """The application an interaction's follow-ups are written under."""
        return self._app_ids.get(bot_id) or str(data.get("application_id") or "")

    def _interaction_key(self, data: dict[str, Any], *, message_id: str | None) -> tuple[str, bool]:
        """The conversation an interaction belongs to, and whether it is in a server."""
        channel = data.get("channel") or {}
        channel_id = str(data.get("channel_id") or channel.get("id") or "")
        if channel:
            self._channels.put(channel_id, _channel_of(channel))
        guild = bool(data.get("guild_id"))
        return self._chat_key(channel_id, guild=guild, message_id=message_id), guild

    async def _on_command(
        self, data: dict[str, Any], bot_id: str, interaction_id: str, token: str
    ) -> None:
        command = data.get("data") or {}
        name = str(command.get("name") or "")
        user = interaction_user(data)
        attachments: list[IncomingAttachment] = []
        if command.get("type") == 3 and name == ASK_ABOUT:
            target = (
                (command.get("resolved") or {})
                .get("messages", {})
                .get(str(command.get("target_id")), {})
            )
            key, guild = self._interaction_key(data, message_id=str(command.get("target_id")))
            quoted = "\n".join(f"> {line}" for line in (target.get("content") or "").splitlines())
            if guild and key.endswith(f":{command.get('target_id')}"):
                self._thread_names.put(key, thread_name(target.get("content") or ""))
            await self._answer_interaction(
                interaction_id,
                token,
                {"type": 4, "data": {"content": "On it.", "flags": 64}},
            )
            # Until the answer begins, a reply - a refusal - replaces "On it."
            # rather than opening a thread on somebody else's message.
            self._interactions.put(interaction_id, (self._app_id(data, bot_id), token))
            text = f"Help me with this message:\n{quoted}"
            attachments = _attachments(target)
        elif name == ASK:
            options = command.get("options") or []
            question = str(options[0].get("value") or "") if options else ""
            refusal = await refusal_before_publishing(
                IncomingMessage(
                    platform=self.platform,
                    bot_id=bot_id,
                    platform_user_id=str(user.get("id") or ""),
                    platform_chat_id=str(data.get("channel_id") or ""),
                    chat_type="group" if data.get("guild_id") else "private",
                    text=question,
                    raw=data,
                    platform_username=user.get("username"),
                    platform_display_name=user.get("global_name"),
                    message_id=interaction_id,
                    addressed=True,
                )
            )
            if refusal is not None:
                # Before anything is posted: the question appears in the channel
                # only for somebody the bot would answer.
                await self._answer_interaction(
                    interaction_id, token, {"type": 4, "data": {"content": refusal, "flags": 64}}
                )
                return
            response = await self._call(
                "POST",
                f"/interactions/{interaction_id}/{token}/callback?with_response=true",
                None,
                body={
                    "type": 4,
                    "data": {"content": question, "allowed_mentions": NO_MENTIONS},
                },
            )
            response.raise_for_status()
            posted = ((response.json().get("resource") or {}).get("message") or {}).get("id")
            key, guild = self._interaction_key(data, message_id=posted)
            if guild and posted and key.endswith(f":{posted}"):
                self._thread_names.put(key, thread_name(question))
            text = question
        elif name in _ROUTED_COMMANDS:
            key, guild = self._interaction_key(data, message_id=None)
            if name == "new" and guild and key == str(data.get("channel_id") or ""):
                channel = self._channels.get(key)
                if channel is None or channel.kind not in THREAD_TYPES:
                    # A server channel holds no conversation to start over: each
                    # mention there opens its own thread.
                    await self._answer_interaction(interaction_id, token, NEW_OUTSIDE_THREAD)
                    return
            # Deferred and private: the router's reply is written into it.
            await self._answer_interaction(
                interaction_id, token, {"type": 5, "data": {"flags": 64}}
            )
            self._interactions.put(interaction_id, (self._app_id(data, bot_id), token))
            text = f"/{name}"
        else:
            return
        spawn(
            process_channel_event(
                IncomingMessage(
                    platform=self.platform,
                    bot_id=bot_id,
                    platform_user_id=str(user.get("id") or ""),
                    platform_chat_id=key,
                    chat_type="group" if guild else "private",
                    text=text,
                    raw=data,
                    platform_username=user.get("username"),
                    platform_display_name=user.get("global_name"),
                    message_id=interaction_id,
                    addressed=True,
                    attachments=attachments,
                )
            ),
            name=f"discord-command:{bot_id}",
        )

    async def _on_press(
        self, data: dict[str, Any], bot_id: str, interaction_id: str, token: str
    ) -> None:
        value = pressed_value(data.get("data") or {})
        if value is None:
            return
        rating = read_feedback(value)
        if rating is not None and not rating[1]:
            await self._answer_interaction(interaction_id, token, comment_form(rating[0]))
        else:
            await self._answer_interaction(interaction_id, token, {"type": 6})
        message = data.get("message") or {}
        user = interaction_user(data)
        spawn(
            process_channel_press(
                IncomingPress(
                    platform=self.platform,
                    bot_id=bot_id,
                    platform_user_id=str(user.get("id") or ""),
                    platform_chat_id=str(data.get("channel_id") or ""),
                    value=value,
                    platform_username=user.get("username"),
                    message_id=message.get("id"),
                    prompt_text=message.get("content"),
                    ack_id=token,
                )
            ),
            name=f"discord-press:{bot_id}",
        )

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """Discord reaches this deployment over the Gateway only; there is no webhook to register."""
        return False

    async def delete_webhook(self, bot_token: str) -> bool:
        return False

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """No webhook route accepts Discord traffic, so nothing verifies as Discord's."""
        return False


_SPOKEN_MESSAGE_TYPES = frozenset({0, 19})
"""Discord's `DEFAULT` and `REPLY` message types: what a person wrote, as opposed to a notice."""


def _posted_at(timestamp: object) -> datetime | None:
    """When Discord says a message was posted, or `None` where it did not say."""
    if not isinstance(timestamp, str):
        return None
    try:
        return datetime.fromisoformat(timestamp)
    except ValueError:
        return None


def _attachments(message: dict[str, Any], *, by: str | None = None) -> list[IncomingAttachment]:
    """The files on a message, typed by `attachment_type` and fetched later from the CDN.

    `by` names who posted it when the message was read out of a thread's history.
    """
    return [
        IncomingAttachment(
            filename=str(item.get("filename") or "file"),
            mime_type=attachment_type(
                item.get("content_type"), str(item.get("filename") or "file")
            ),
            size=int(item.get("size") or 0),
            handle=str(item.get("url") or ""),
            author_id=by,
        )
        for item in message.get("attachments") or []
        if item.get("url")
    ]


def _conversation_root(message: dict[str, Any], own: str | None) -> str | None:
    """The message a server conversation outside a thread is keyed on: this one, mostly.

    A reply to the bot continues the conversation it replied into. Where the bot
    may not open threads, each answer is a reply to the question, so keying the
    follow-up on itself would start every turn afresh. The bot's message names
    the question it answered; one that answered nothing - the question `/ask`
    posts - is the question.
    """
    replied = message.get("referenced_message") or {}
    if own and (replied.get("author") or {}).get("id") == own:
        return (replied.get("message_reference") or {}).get("message_id") or replied.get("id")
    return message.get("id")


def _error_code(response: httpx.Response) -> int | None:
    """Discord's own error code from a failed call's body, which says more than its status."""
    try:
        code = response.json().get("code")
    except ValueError:
        return None
    return code if isinstance(code, int) else None
