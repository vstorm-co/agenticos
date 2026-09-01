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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from app.agents.capabilities.channel_tools import (
    ChannelDetails,
    ChannelMember,
    ChannelPost,
    ChannelSummary,
)
from app.core.security import encode_untrusted
from app.db.session import get_db_context
from app.services.channels import connection_state
from app.services.channels.base import (
    ChannelAdapter,
    IncomingAttachment,
    IncomingMessage,
    OutgoingMessage,
    split_thread,
    thread_key,
)
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.router import ChannelMessageRouter

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

_SPOKEN_SUBTYPES = frozenset({"file_share"})
"""Message subtypes that are still somebody talking to the bot.

Slack stamps a `subtype` on a `message` event for two unrelated reasons: the
platform describing the channel - an edit, a deletion, a join, a topic change -
and a person sending something richer than plain text. Refusing every subtype
treats the second as the first, and `file_share` is the one that costs: a message
with a file attached carries it, so **every image and document sent to a Slack bot
was dropped before `_attachments` ever ran** - with the whole attachment path
written, tested and unreachable, and the caption on the file discarded with it.

An allowlist rather than a deny-list of the platform's own subtypes, because the
platform adds subtypes and the ones worth answering are the short list.
`thread_broadcast` is deliberately not here: it is a thread reply *also* posted to
the channel, so it arrives beside the reply itself and answering both would be
answering twice.
"""

_MEMBERSHIP_PAGES = 50
"""How far `is_channel_member` will walk `conversations.members`.

At Slack's 1000 ids per page this covers a fifty-thousand-member channel,
which is a bound on a runaway cursor rather than on any real room.
"""


class SlackAdapter(ChannelAdapter):
    """Concrete Slack adapter using slack-sdk."""

    platform: str = "slack"

    def __init__(self) -> None:
        # One client per adapter for the file downloads below, not one per call,
        # so fetching several attachments from one Slack turn reuses the
        # connection rather than handshaking each time (#952). Sends go through
        # the slack-sdk WebClient, which is per bot token, not through this.
        self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._socket_tasks: dict[str, asyncio.Task[None]] = {}
        # Each bot is its own Slack app, so Socket Mode connects with that
        # bot's xapp- token. Registered before polling starts, the same way
        # Mattermost's per-bot server address is.
        self._app_tokens: dict[str, str] = {}

    def remember_app_token(self, bot_id: str, app_token: str) -> None:
        """Register the app-level token Socket Mode will connect with."""
        self._app_tokens[bot_id] = app_token

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _web(bot_token: str) -> "AsyncWebClient":
        """A Web API client for one bot's token.

        The `slack_sdk` import is deferred to the call rather than the module so a
        deployment that runs no Slack bot does not pay for the SDK at import time,
        which is why every caller builds a client per request rather than holding
        one on the adapter.
        """
        from slack_sdk.web.async_client import AsyncWebClient

        return AsyncWebClient(token=bot_token)

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Post the message that will become the answer, and return its `ts`.

        A Slack message is addressed by the timestamp it was posted at, so that
        is the handle - and in a thread it is *also* what a reply is keyed to,
        which is why the channel and the thread are split apart here the same way
        `send_message` splits them.
        """
        channel, thread_ts = split_thread(msg.platform_chat_id)
        kwargs: dict[str, Any] = {"channel": channel, "text": msg.text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        response = await self._web(bot_token).chat_postMessage(**kwargs)
        posted = response.get("ts")
        return str(posted) if posted else None

    async def update_reply(self, bot_token: str, msg: OutgoingMessage, handle: str) -> None:
        """Rewrite a message already in the channel."""
        channel, _thread_ts = split_thread(msg.platform_chat_id)
        await self._web(bot_token).chat_update(channel=channel, ts=handle, text=msg.text)

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Send a reply back to Slack via the Web API."""
        client = self._web(bot_token)

        channel, thread_ts = split_thread(msg.platform_chat_id)

        kwargs: dict[str, Any] = {
            "channel": channel,
            "text": msg.text,
        }
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
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

    #
    # `channels:read`, `groups:read` and `channels:history` on the Slack app -
    # scopes an admin grants when they install it. The bot sees what the app was
    # installed with and nothing beyond it, which is the same boundary the other
    # two adapters keep.

    @staticmethod
    def _posted_at(ts: Any) -> datetime | None:
        """A Slack `ts` as a datetime, or `None` when it is not a timestamp.

        Slack's message id *is* its timestamp, seconds since the epoch with a
        sequence number after the point. `None` rather than a raise: this
        decorates a line of history, and a post with an unreadable timestamp is
        still a post somebody wrote.
        """
        try:
            return datetime.fromtimestamp(float(ts), UTC)
        except (TypeError, ValueError):
            return None

    async def channel_details(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None
    ) -> ChannelDetails:
        """`conversations.info`, with the member count Slack only sends on request."""
        response = await self._web(bot_token).conversations_info(
            channel=channel_id, include_num_members=True
        )
        found: dict[str, Any] = response.get("channel") or {}
        return ChannelDetails(
            channel_id=str(found.get("id") or channel_id),
            name=str(found.get("name") or channel_id),
            purpose=str((found.get("purpose") or {}).get("value") or "") or None,
            topic=str((found.get("topic") or {}).get("value") or "") or None,
            is_private=bool(found.get("is_private")),
            member_count=(None if found.get("num_members") is None else int(found["num_members"])),
        )

    async def channel_members(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None, limit: int
    ) -> list[ChannelMember]:
        """`conversations.members`, then one `users.info` per id, concurrently.

        Slack has no bulk lookup by id - `users.list` answers with the whole
        workspace - so the ids are resolved one at a time. Concurrently and
        bounded by `limit`, because this runs inside a tool call somebody is
        waiting on, and serially it is the length of the channel in round trips.
        """
        client = self._web(bot_token)
        response = await client.conversations_members(channel=channel_id, limit=limit)
        user_ids = [str(user_id) for user_id in (response.get("members") or [])][:limit]
        if not user_ids:
            return []

        found = await asyncio.gather(*(client.users_info(user=user_id) for user_id in user_ids))
        members: list[ChannelMember] = []
        for user_id, entry in zip(user_ids, found, strict=True):
            user: dict[str, Any] = entry.get("user") or {}
            profile: dict[str, Any] = user.get("profile") or {}
            members.append(
                ChannelMember(
                    user_id=user_id,
                    username=str(user.get("name") or "") or None,
                    display_name=str(profile.get("display_name") or profile.get("real_name") or "")
                    or None,
                    is_bot=bool(user.get("is_bot")),
                    role="admin" if user.get("is_admin") else "member",
                )
            )
        return members

    async def is_channel_member(
        self, bot_token: str, channel_id: str, platform_user_id: str, *, api_base_url: str | None
    ) -> bool:
        """`conversations.members`, paged until the account is found or the list ends.

        Slack has no per-account membership call for a bot token, so the page
        walk is the question - full pages of ids only, never the `users.info`
        fan-out `channel_members` does, because nobody here needs a name. The
        page cap exists so a pathological cursor cannot loop forever; a channel
        bigger than it answers "not a member", logged, which is the participant
        model's safe default rather than a claim about the room.
        """
        client = self._web(bot_token)
        cursor: str | None = None
        for _ in range(_MEMBERSHIP_PAGES):
            response = await client.conversations_members(
                channel=channel_id, limit=1000, cursor=cursor
            )
            if platform_user_id in {str(found) for found in (response.get("members") or [])}:
                return True
            cursor = str((response.get("response_metadata") or {}).get("next_cursor") or "") or None
            if cursor is None:
                return False
        logger.warning(
            "Slack channel %s exceeded %d membership pages; treating %s as not a member",
            channel_id,
            _MEMBERSHIP_PAGES,
            platform_user_id,
        )
        return False

    async def search_channels(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None, query: str, limit: int
    ) -> list[ChannelSummary]:
        """`conversations.list`, matched here rather than by Slack.

        Slack's `search.messages` needs a *user* token and searches contents,
        which is not what this asks; there is no channel-name search for a bot
        token. So the list comes back and the match happens locally, over the
        name and the purpose - the two fields somebody would have typed into a
        search box.
        """
        response = await self._web(bot_token).conversations_list(
            types="public_channel,private_channel", limit=1000, exclude_archived=True
        )
        needle = query.casefold()
        found: list[ChannelSummary] = []
        for entry in response.get("channels") or []:
            purpose = str((entry.get("purpose") or {}).get("value") or "")
            name = str(entry.get("name") or "")
            if needle not in name.casefold() and needle not in purpose.casefold():
                continue
            found.append(
                ChannelSummary(
                    channel_id=str(entry.get("id")),
                    name=name,
                    purpose=purpose or None,
                    is_private=bool(entry.get("is_private")),
                )
            )
            if len(found) == limit:
                break
        return found

    async def channel_history(
        self,
        bot_token: str,
        channel_id: str,
        *,
        api_base_url: str | None,
        limit: int,
        thread_id: str | None = None,
    ) -> list[ChannelPost]:
        """The recent transcript, reversed so the newest is last.

        `conversations.replies` for a thread and `conversations.history` for the
        channel, because on Slack those are two different transcripts and the one
        the agent is in is the thread. Asked for the channel while answering
        inside a thread, "summarise what we decided above" summarised whatever
        else the room had been saying (#1353).

        `replies` returns the thread oldest-first with the parent at the top,
        which is already the order a person reads - the reversal below applies to
        `history`, which comes back newest-first.

        Authors stay as Slack ids. Resolving them would be one `users.info` per
        distinct speaker on top of the history call, and a transcript reads well
        enough with `U01ABC` where a name would go - `list_channel_members` is
        the tool for turning ids into people, and the model can call it when the
        answer actually depends on who spoke.
        """
        client = self._web(bot_token)
        if thread_id:
            replies = await client.conversations_replies(
                channel=channel_id, ts=thread_id, limit=limit
            )
            messages = list(replies.get("messages") or [])
        else:
            response = await client.conversations_history(channel=channel_id, limit=limit)
            messages = list(reversed(response.get("messages") or []))
        return [
            ChannelPost(
                author=str(message.get("user") or message.get("bot_id") or "unknown"),
                text=str(message.get("text") or ""),
                posted_at=self._posted_at(message.get("ts")),
                post_id=str(message.get("ts")) if message.get("ts") else None,
                author_id=(str(message.get("user")) if message.get("user") else None),
            )
            for message in messages
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
        """The files on a thread's earlier messages, oldest first.

        `conversations.replies` again rather than a shape carried out of
        `channel_history`: that answers the capability's contract, which holds no
        handles, and reading the thread twice on the one turn that opens a
        conversation is cheaper than inverting the layering to avoid it.

        `_attachments` is the same reader the live path uses, because a message in
        a thread's history carries `files` exactly as the event did - so a photo
        posted before the bot arrived is described the same way as one posted to
        it.
        """
        replies = await self._web(bot_token).conversations_replies(
            channel=channel_id, ts=thread_id, limit=limit
        )
        found: list[IncomingAttachment] = []
        for message in replies.get("messages") or []:
            if message.get("bot_id"):
                continue
            found.extend(self._attachments(message))
        return found

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
            except ChannelNotConfigured as exc:
                # Not a crash and not something a retry fixes: an operator has
                # to add the token. Retrying would be the spin all over again.
                logger.warning("Slack Socket Mode not started for bot %s", bot_id)
                # Its own message, because this one is written here rather than by
                # a vendor: it names the credential to add. Recorded so the row
                # says so - a WARNING in a container was the only evidence, and
                # `/channels` showed the bot as healthy (#1351).
                await connection_state.record_down(bot_id, str(exc))
                return
            except Exception:
                logger.exception("Slack Socket Mode crashed for bot %s, restarting in 5s", bot_id)
                await connection_state.record_down(
                    bot_id,
                    "The Slack connection keeps failing. Check the app-level token "
                    "and that Socket Mode is enabled in the Slack app.",
                )
            await asyncio.sleep(5)

    async def _run_socket_mode(self, bot_id: str, bot_token: str) -> None:
        """Run one Socket Mode session."""
        try:
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.socket_mode.request import SocketModeRequest
            from slack_sdk.socket_mode.response import SocketModeResponse
        except ImportError as exc:
            # Names the real dependency. It used to name `slack-sdk[socket-mode]`,
            # an extra slack-sdk has never had - the only one is `optional` - so
            # the one instruction this refusal existed to give could not be
            # followed. `aiohttp` is declared in pyproject.toml for this import.
            raise ChannelNotConfigured(
                message=(
                    "Slack Socket Mode needs aiohttp, which this environment does "
                    "not have. Install it, or reinstall the backend's dependencies."
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
            web_client=self._web(bot_token),
        )

        async def handler(client_: Any, req: SocketModeRequest) -> None:
            await client_.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            if req.type == "events_api":
                # The whole payload, not `payload["event"]`. Slack states which
                # installation an event was delivered for *beside* the event, so
                # unwrapping here threw away the only thing that says whether the
                # bot was named - and every Socket Mode message then looked like a
                # platform that does not report mentions, which the router answers.
                await self._handle_event(req.payload, bot_id)

        client.socket_mode_request_listeners.append(handler)  # type: ignore[arg-type]
        await client.connect()
        await connection_state.record_up(bot_id)
        # Blocks for the life of the connection, as the bare sleep loop it
        # replaces did - and re-stamps the entry while it waits, so a bot nobody
        # has messaged for fifteen minutes does not read `unknown` (#1351).
        await connection_state.heartbeat(bot_id)

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
            "v0="
            + hmac.new(secret.encode(), encode_untrusted(base_string), hashlib.sha256).hexdigest()
        )

        return hmac.compare_digest(computed.encode(), encode_untrusted(signature))

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """Parse a Slack event payload into IncomingMessage.

        Handles `message` events (direct messages and channel messages).
        Ignores bot messages, edits, deletions and joins.
        Thread replies get thread_ts folded into platform_chat_id.
        """
        event: dict[str, Any] = raw_payload.get("event", raw_payload)

        event_type: str = event.get("type", "")
        if event_type != "message" and event_type != "app_mention":
            return None

        subtype = event.get("subtype")
        if event.get("bot_id") or (subtype and subtype not in _SPOKEN_SUBTYPES):
            return None

        attachments = self._attachments(event)
        text: str = event.get("text") or ""
        if not text and not attachments:
            return None

        addressed = self._addressed(raw_payload, event)
        # After `_addressed`, which is what the token is for. The model is the
        # addressee, so being told its own id is noise: `<@U09MQFTBHTV> try again`
        # is a question about a Slack id as far as it can tell, and an answer
        # about one is what it gives. Somebody else's mention stays - "ask
        # <@UADA>" is a fact about the request, not an envelope.
        text = self._without_own_mention(text, raw_payload)

        user_id: str = event.get("user", "")
        channel: str = event.get("channel", "")
        channel_type: str = event.get("channel_type", "channel")
        thread_ts: str | None = event.get("thread_ts")
        message_ts: str | None = event.get("ts")

        # `im` alone. An `mpim` is a direct message with several people in it,
        # which makes it a room: the bot is one of its members, so a message
        # naming nobody names nobody, and the account-linking URL - a bearer
        # credential - must not be posted where the others can read it.
        chat_type = "private" if channel_type == "im" else "group"

        platform_chat_id = thread_key(
            channel,
            thread_id=thread_ts or "",
            message_id=message_ts,
        )

        return IncomingMessage(
            platform="slack",
            bot_id=bot_id,
            platform_user_id=user_id,
            one_to_one=channel_type == "im",
            platform_chat_id=platform_chat_id,
            chat_type=chat_type,
            text=text,
            raw=raw_payload,
            platform_username=None,
            platform_display_name=None,
            message_id=message_ts,
            attachments=attachments,
            addressed=addressed,
        )

    def _without_own_mention(self, text: str, raw_payload: dict[str, Any]) -> str:
        """The message with the bot's own mention token taken out.

        Slack substitutes `<@U0123>` for a real mention, and that token is the
        envelope rather than the message: the agent *is* the addressee, so being
        handed its own id as content is being asked about a Slack id. It answered
        about one, saying it could see "just the mention" of a message that also
        said `try again`.

        Only the bot's own, and only when the payload says which that is. Somebody
        else's mention is information about the request - "ask <@UADA> about
        billing" - and stripping it would delete the point of the sentence.

        Whitespace is collapsed after the removal so a leading mention does not
        leave the prompt starting with a space, and a mid-sentence one does not
        leave two.
        """
        own = self._own_user_id(raw_payload)
        if not own:
            return text
        return " ".join(text.replace(f"<@{own}>", " ").split())

    @staticmethod
    def _own_user_id(raw_payload: dict[str, Any]) -> str | None:
        """The bot user this event was delivered for, from the payload itself.

        Slack states the installation an event belongs to, which is what makes
        this readable in a synchronous parser: Mattermost has to resolve its own
        account over the API and cache it per session, and there is nothing to
        resolve here. `authorizations` is the current field and `authed_users`
        the one older payloads carry.
        """
        authorizations = raw_payload.get("authorizations")
        if isinstance(authorizations, list):
            for entry in authorizations:
                if isinstance(entry, dict) and entry.get("user_id"):
                    return str(entry["user_id"])
        authed_users = raw_payload.get("authed_users")
        if isinstance(authed_users, list) and authed_users:
            return str(authed_users[0])
        return None

    def _addressed(self, raw_payload: dict[str, Any], event: dict[str, Any]) -> bool | None:
        """Whether this message named the bot, as far as the payload will say.

        Slack delivers what the app subscribed to, and `message.channels` is
        every message in every channel the bot is in - so with that subscription
        an unanswered question is not the same thing as no question, and a bot
        that answered everything talked over the team it was invited to. Reading
        it here rather than dropping the subscription keeps the whole
        conversation arriving, which is what an agent deciding for itself
        whether to answer will need.

        `app_mention` is delivered only when the bot was named, so it needs
        nothing read.

        A `message` event is matched on the bot's own id appearing in the text as
        `<@U0123>`, which is what Slack substitutes for a real mention. On the id
        rather than on a name, for Mattermost's reason: `@ada` is somebody whose
        display name the bot cannot resolve, and a bot called `bot` must not
        answer the word "robot". A handle somebody typed without letting Slack
        resolve it stays plain text and is not a mention here either - the
        platform did not deliver one.

        `None` where the payload never said which installation it was for, which
        the router reads as "the platform did not say" and answers as it did
        before. Going quiet on a payload we cannot read is the worse failure.
        """
        if event.get("type") == "app_mention":
            return True
        own = self._own_user_id(raw_payload)
        if own is None:
            return None
        return f"<@{own}>" in (event.get("text") or "")

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
        response = await self._http.get(
            attachment.handle, headers={"Authorization": f"Bearer {bot_token}"}
        )
        response.raise_for_status()
        if response.headers.get("content-type", "").startswith("text/html"):
            raise ValueError(
                f"Slack answered with a sign-in page for {attachment.filename}; "
                "the bot token cannot read that file."
            )
        return response.content

    async def _handle_event(self, payload: dict[str, Any], bot_id: str) -> None:
        """Route one `events_api` payload, whole.

        The **payload**, not the event inside it. It used to take the event and
        rewrap it as `{"event": event}`, which reads identically for the text and
        the channel and silently drops `authorizations` - the field naming the bot
        user this was delivered for, and so the only way a synchronous parser can
        tell whether the bot was named. Every Socket Mode message therefore
        reached the router with `addressed` unset, which it answers, so the bot
        replied to everything said in a channel it had been invited to.
        """
        incoming = self.parse_incoming(payload, bot_id)
        if incoming is None:
            return

        router = ChannelMessageRouter()

        async with get_db_context() as db:
            await router.route(incoming, db)
