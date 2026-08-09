"""Channel message router - processes incoming messages end-to-end."""

import asyncio
import json
import logging
import re
import time
from typing import Any

from app.core.exceptions import AppException, AuthorizationError, BadRequestError
from app.repositories import (
    channel_bot_repo,
    channel_identity_repo,
    channel_session_repo,
    conversation_repo,
)
from app.services.agent import build_message_history
from app.services.channel_bot import unseal_bot_token
from app.services.channel_link import ChannelLinkService
from app.services.channels import get_adapter
from app.services.channels.attachments import ChannelAttachmentService
from app.services.channels.base import IncomingMessage, OutgoingAttachment, OutgoingMessage
from app.services.channels.mentions import ChannelAgentRouter, UnaddressedMessage

logger = logging.getLogger(__name__)

# key format: "{bot_id}:{identity_id}", value = (count, window_start_ts)
_rate_buckets: dict[str, tuple[int, float]] = {}

_DEFAULT_RPM = 10  # requests per minute

# In group chats multiple users can message simultaneously. Without a lock the router
# would race: duplicate ChannelSession creation, interleaved agent calls, rate-limit races.
# Key = (bot_id, platform_chat_id); 1-on-1 chats also acquire it but contention is negligible.
_chat_locks: dict[str, asyncio.Lock] = {}


_SLASHLESS = re.compile(r"^link$", re.IGNORECASE)
"""A command a platform would have eaten before we saw it.

Mattermost parses a leading `/` itself: typing `/link` in a Mattermost chat
answers *"command with a trigger of '/link' not found"* and never delivers
anything. Since connecting an account is the thing somebody does before any
channel will answer them, that was the one command that had to survive it.

Only `link`, and only when it is the whole message. "link" is an ordinary word in
English and in Polish, so anything around it - "link do dokumentu?" - is a
question for the agent rather than a command.
"""


def _as_command(text: str) -> str:
    """The message as a command, restoring a slash the platform swallowed."""
    stripped = text.strip()
    match = _SLASHLESS.match(stripped)
    return f"/{stripped}" if match else stripped


def _get_chat_lock(bot_id: str, chat_id: str) -> asyncio.Lock:
    """Return (or create) the asyncio.Lock for a bot + chat pair."""
    key = f"{bot_id}:{chat_id}"
    if key not in _chat_locks:
        _chat_locks[key] = asyncio.Lock()
    return _chat_locks[key]


def _kept_back(paths: list[str]) -> list[str]:
    """What the agent produced and the reply could not carry, as one sentence.

    A bare list of workspace paths under an answer reads as output. This says why
    they are there and where they still are, which is the difference between an
    explanation and a puzzle.
    """
    if not paths:
        return []
    return [
        f"({', '.join(paths)} stayed in the workspace - too large to post here, "
        "or past the file limit for one reply.)"
    ]


class ChannelMessageRouter:
    """Process an incoming channel message end-to-end."""

    async def route(self, incoming: IncomingMessage, db: Any) -> None:
        """Acquire per-chat lock, then process the message.

        The lock ensures that concurrent messages in the same group chat
        are processed sequentially - no duplicate sessions, no interleaved
        agent calls.
        """
        lock = _get_chat_lock(incoming.bot_id, incoming.platform_chat_id)
        async with lock:
            await self._route_inner(incoming, db)

    async def _route_inner(self, incoming: IncomingMessage, db: Any) -> None:
        """Process an incoming channel message end-to-end.

        Steps:
            1. Load bot config from DB.
            2. Check access policy.
            3. Handle commands (/start, /new, /help, /link, /project, /unlink).
            4. Resolve or create ChannelIdentity.
            5. Resolve or create ChannelSession (+ Conversation).
            6. Rate-limit check.
            7. Hand an `@handle` message to that agent and stop.
            8. Otherwise run the bot's only exposed agent.
            9. Send reply via adapter.
        """
        bot = await channel_bot_repo.get_for_inbound(db, incoming.bot_id)
        if not bot or not bot.is_active:
            logger.debug("Bot %s not found or inactive - ignoring", incoming.bot_id)
            return

        try:
            self._check_access(incoming, bot)
        except AuthorizationError as exc:
            await self._send_reply(bot, incoming, exc.message)
            return

        command_reply = await self._handle_command(incoming.text, incoming, bot, db)
        if command_reply is not None:
            await self._send_reply(bot, incoming, command_reply)
            return

        try:
            identity = await self._resolve_identity(incoming, bot, db)
        except AuthorizationError as exc:
            await self._send_reply(bot, incoming, exc.message)
            return

        if identity.user_id is None:
            await self._send_reply(bot, incoming, await self._invite_to_link(incoming, db))
            return

        session = await self._resolve_session(incoming, bot, identity, db)

        try:
            self._check_rate_limit(bot, str(identity.id))
        except BadRequestError as exc:
            await self._send_reply(bot, incoming, exc.message)
            return

        if await self._answer_mention(incoming, bot, identity, session, db):
            return

        files, file_refusals = await self._receive_files(db, bot, incoming, identity)

        # Loaded before the run, so the turn being run is the prompt and
        # everything before it is the history. The turn itself is written by the
        # runner, which is also what records the tool calls, the model and the
        # version this bot's own write dropped.
        history = await self._load_history(db, session.conversation_id)
        try:
            answered = await ChannelAgentRouter(db).answer_default(
                incoming.text,
                platform=incoming.platform,
                organization_id=bot.organization_id,
                bot_id=bot.id,
                user_id=identity.user_id,
                conversation_id=session.conversation_id,
                platform_chat_id=incoming.platform_chat_id,
                # What this bot says about what a turn cost, and how many turns
                # this chat has had - `every_n` counts per chat, because "every
                # tenth message" is a question about this conversation and not
                # about whichever channel happened to be tenth across the bot.
                usage_reporting=bot.usage_reporting,
                turn=session.turn_count,
                attachments=files,
                message_history=build_message_history(history),
            )
        except AppException as exc:
            # A refusal - no agent exposed, several to choose from, an unlinked
            # sender - is the platform answering, not a crash. The message says
            # what to do next.
            await self._send_reply(bot, incoming, exc.message)
            return
        except Exception:
            logger.exception("Agent run failed for bot %s", incoming.bot_id)
            await self._send_reply(bot, incoming, "Sorry, something went wrong. Please try again.")
            return

        # The notes are about what this reply could not carry - a file too large
        # for Slack - so they belong to the delivery and not to the transcript,
        # which holds what the agent actually said.
        answer = self._with_notes(answered.text, file_refusals, _kept_back(answered.refused))
        await self._send_reply(
            bot,
            incoming,
            answer or "That needs approval before it can run - check the approvals queue.",
            answered.attachments,
            image_png=answered.image_png,
        )

    async def _answer_mention(
        self, incoming: IncomingMessage, bot: Any, identity: Any, session: Any, db: Any
    ) -> bool:
        """Answer `@handle …` with that agent, and report whether we did.

        Placed after the session is resolved so a mentioned agent shares the
        thread's conversation, and before the bot's own assistant so a named
        agent always wins: someone who typed a handle asked for that agent, and
        silently answering as something else is worse than not answering.

        A refusal - unlinked account, unknown handle, an agent they cannot see,
        an agent nobody exposed on this bot - is reported to the sender and still
        counts as handled. Falling through to the default assistant would answer
        a question that was not asked.
        """
        files, file_refusals = await self._receive_files(db, bot, incoming, identity)
        try:
            answered = await ChannelAgentRouter(db).answer(
                incoming.text,
                platform=incoming.platform,
                organization_id=bot.organization_id,
                bot_id=bot.id,
                user_id=identity.user_id,
                conversation_id=session.conversation_id,
                platform_chat_id=incoming.platform_chat_id,
                usage_reporting=bot.usage_reporting,
                turn=session.turn_count,
                attachments=files,
            )
        except UnaddressedMessage:
            return False
        except AppException as exc:
            await self._send_reply(bot, incoming, exc.message)
            return True

        answer = self._with_notes(answered.text, file_refusals, _kept_back(answered.refused))
        await self._send_reply(
            bot,
            incoming,
            answer or "That needs approval before it can run - check the approvals queue.",
            answered.attachments,
            image_png=answered.image_png,
        )
        return True

    async def _receive_files(
        self, db: Any, bot: Any, incoming: IncomingMessage, identity: Any
    ) -> tuple[list[Any], list[str]]:
        """Fetch, validate and store what arrived with the message.

        Returns the rows and a line per file that did not make it, for the reply to
        carry. A message with no attachments costs nothing here - not even a token
        decryption - which is the common case.

        An unlinked sender is not handled specially: a stored file belongs to a
        user row, and the agent router refuses an unlinked sender anyway. Without
        the check this would raise where the refusal reads better.
        """
        if not incoming.attachments:
            return [], []
        if identity.user_id is None:
            return [], ["Files can only be accepted once you have run /link."]

        adapter = get_adapter(incoming.platform)
        return await ChannelAttachmentService(db).receive(
            adapter,
            unseal_bot_token(bot),
            incoming.attachments,
            user_id=identity.user_id,
        )

    @staticmethod
    def _with_notes(answer: str, *notes: list[str]) -> str:
        """The answer, with what could not be delivered said out loud under it.

        Said rather than logged: a file the platform refused and a file the agent
        never wrote look identical to whoever asked for it, and an agent that
        believes its attachment was delivered will tell them it was.
        """
        lines = [line for group in notes for line in group]
        if not lines or not answer:
            return answer
        return answer + "\n\n" + "\n".join(lines)

    @staticmethod
    def _parse_policy(bot: Any) -> dict[str, Any]:
        """Return bot.access_policy as a dict regardless of storage format.

        SQLite stores access_policy as a JSON string; PostgreSQL/MongoDB store
        it natively as a dict. This helper normalises both cases.
        """
        raw = bot.access_policy or {}
        if isinstance(raw, str):
            return json.loads(raw) if raw else {}
        return raw

    def _check_access(self, incoming: IncomingMessage, bot: Any) -> None:
        """Enforce access policy. Raises AuthorizationError if denied."""
        policy: dict[str, Any] = self._parse_policy(bot)
        mode: str = policy.get("mode", "open")

        if mode == "whitelist":
            whitelist: list[str] = [str(x) for x in policy.get("whitelist", [])]
            if str(incoming.platform_user_id) not in whitelist:
                raise AuthorizationError(
                    message=policy.get("denied_message", "You are not authorised to use this bot.")
                )
        elif mode == "group_only":
            allowed: list[str] = [str(x) for x in policy.get("allowed_groups", [])]
            if str(incoming.platform_chat_id) not in allowed:
                raise AuthorizationError(
                    message=policy.get(
                        "denied_message", "This bot is only available in specific groups."
                    )
                )
        # "open" and "jwt_linked" pass through here; jwt_linked is enforced at identity resolution

    async def _invite_to_link(self, incoming: IncomingMessage, db: Any) -> str:
        """What to answer somebody whose chat account is nobody's yet.

        A run belongs to a person - their budget, their permissions, their name
        on the audit entry - so an unlinked sender is refused whatever the bot's
        access policy says. The refusal carries the way out rather than
        describing it: a URL they open while already signed in.

        **Only in a direct message.** The URL is a bearer credential: whoever
        opens it claims this chat account. In a channel everybody can read it,
        so a channel gets the instruction and the direct message gets the link.
        """
        if incoming.chat_type != "private":
            return (
                "Send me a direct message to connect your account - the link is "
                "personal, so it does not belong in a channel."
            )
        url = await ChannelLinkService(db).request(incoming)
        return (
            f"Connect your account to start: {url}\n\nThe link is yours alone and expires shortly."
        )

    async def _handle_command(
        self, text: str, incoming: IncomingMessage, bot: Any, db: Any
    ) -> str | None:
        """Handle bot commands. Returns reply text or None if not a command."""
        text = _as_command(text)
        if not text.startswith("/"):
            return None

        # Only the first word: no command takes an argument any more. `/link`
        # was the one that did, and it took a code somebody copied out of the
        # dashboard - which is the flow this replaced.
        cmd = text.split(maxsplit=1)[0].lower().split("@")[0]  # strip @botname suffix

        if cmd == "/start":
            return (
                bot.welcome_message
                if hasattr(bot, "welcome_message") and bot.welcome_message
                else (
                    f"Welcome! I'm {bot.name}. How can I help you today?\n\n"
                    "Use /help to see available commands."
                )
            )

        if cmd == "/help":
            return (
                "Available commands:\n"
                "/start - Show welcome message\n"
                "/new - Start a new conversation\n"
                "/help - Show this help\n"
                "/link - Connect your chat account to your account here\n"
                "/unlink - Unlink your account"
            )

        if cmd == "/new":
            session = await channel_session_repo.get_by_bot_and_chat(
                db, bot_id=bot.id, platform_chat_id=incoming.platform_chat_id
            )
            if session:
                identity = await channel_identity_repo.get_by_id(db, session.identity_id)
                new_conv = await conversation_repo.create_conversation(
                    db,
                    title=f"{incoming.platform.capitalize()} Chat",
                    user_id=identity.user_id if identity else None,
                    organization_id=bot.organization_id,
                )
                await channel_session_repo.update(
                    db, db_session=session, update_data={"conversation_id": new_conv.id}
                )
            return "New conversation started! How can I help you?"

        if cmd == "/link":
            # Takes no argument any more: it asks for a fresh link rather than
            # carrying a code somebody copied. Kept because "how do I connect
            # this?" is a question people ask in words, and because a URL that
            # expired needs a way to ask for another.
            try:
                return await self._invite_to_link(incoming, db)
            except Exception:
                logger.exception("Unexpected error processing /link command")
                return "A system error occurred. Please try again later."

        if cmd == "/unlink":
            identity = await channel_identity_repo.get_by_platform_user(
                db,
                platform=incoming.platform,
                platform_user_id=incoming.platform_user_id,
            )
            if identity:
                await channel_identity_repo.update(
                    db, db_identity=identity, update_data={"user_id": None}
                )
            return "Your account has been unlinked."

        return None

    async def _resolve_identity(self, incoming: IncomingMessage, bot: Any, db: Any) -> Any:
        """Get or create ChannelIdentity for this platform user."""
        policy: dict[str, Any] = self._parse_policy(bot)
        mode: str = policy.get("mode", "open")

        identity = await channel_identity_repo.get_by_platform_user(
            db,
            platform=incoming.platform,
            platform_user_id=incoming.platform_user_id,
        )
        if not identity:
            identity = await channel_identity_repo.create(
                db,
                platform=incoming.platform,
                platform_user_id=incoming.platform_user_id,
                platform_username=incoming.platform_username,
                platform_display_name=incoming.platform_display_name,
                user_id=None,
            )

        if mode == "jwt_linked" and policy.get("require_link", False) and not identity.user_id:
            raise AuthorizationError(
                message="Please /link your account first before using this bot."
            )

        return identity

    async def _resolve_session(
        self, incoming: IncomingMessage, bot: Any, identity: Any, db: Any
    ) -> Any:
        """Get or create ChannelSession (+ backing Conversation) for this bot+chat."""

        session = await channel_session_repo.get_by_bot_and_chat(
            db, bot_id=bot.id, platform_chat_id=incoming.platform_chat_id
        )
        if not session:
            # The conversation belongs to the organization that owns the bot -
            # not to the linked user's personal org. A Slack channel is the
            # tenant's workspace, and whoever happens to speak in it does not
            # move the conversation into their own org.
            conv = await conversation_repo.create_conversation(
                db,
                title=f"{incoming.platform.capitalize()} Chat",
                user_id=identity.user_id,
                organization_id=bot.organization_id,
            )
            session = await channel_session_repo.create(
                db,
                bot_id=bot.id,
                identity_id=identity.id,
                platform_chat_id=incoming.platform_chat_id,
                conversation_id=conv.id,
            )
        # Records that this chat had a turn, which is what "report usage every n
        # messages" counts. Here rather than after the answer, because a turn that
        # failed still happened - a counter that only advanced on success would
        # drift quietly against the messages people actually sent.
        return await channel_session_repo.touch(db, session)

    def _check_rate_limit(self, bot: Any, identity_id: str) -> None:
        """In-memory token-bucket rate limiter.

        Uses a module-level dict. Default: 10 req/minute from
        `bot.access_policy.rate_limit_rpm`.

        Raises:
            BadRequestError: If the rate limit is exceeded.
        """
        policy: dict[str, Any] = self._parse_policy(bot)
        rpm: int = int(policy.get("rate_limit_rpm", _DEFAULT_RPM))
        window: float = 60.0

        key = f"{bot.id}:{identity_id}"
        now = time.monotonic()

        if key in _rate_buckets:
            count, window_start = _rate_buckets[key]
            if now - window_start < window:
                if count >= rpm:
                    raise BadRequestError(message="Rate limit exceeded. Please slow down.")
                _rate_buckets[key] = (count + 1, window_start)
            else:
                # Window expired - reset
                _rate_buckets[key] = (1, now)
        else:
            _rate_buckets[key] = (1, now)

    async def _send_reply(
        self,
        bot: Any,
        incoming: IncomingMessage,
        text: str,
        attachments: list[OutgoingAttachment] | None = None,
        *,
        image_png: bytes | None = None,
    ) -> None:
        """Decrypt the bot token and send a reply via the appropriate adapter.

        A chart travels as `image_png` rather than as an attachment: every
        adapter posts it as a picture beside the text, where an attachment is
        something to download.
        """
        try:
            adapter = get_adapter(incoming.platform)
            decrypted_token = unseal_bot_token(bot)
            out = OutgoingMessage(
                platform_chat_id=incoming.platform_chat_id,
                text=text,
                parse_mode="Markdown",
                reply_to_message_id=incoming.message_id,
                api_base_url=getattr(bot, "api_base_url", None),
                attachments=attachments or [],
                image_png=image_png,
            )
            await adapter.send_message(decrypted_token, out)
        except Exception:
            logger.exception(
                "Failed to send reply for bot %s to chat %s",
                incoming.bot_id,
                incoming.platform_chat_id,
            )

    @staticmethod
    async def _load_history(db: Any, conversation_id: Any) -> list[dict[str, str]]:
        """The channel thread so far, oldest first, as role/content dicts."""
        messages = await conversation_repo.get_messages_by_conversation(
            db,
            conversation_id=conversation_id,
            skip=0,
            limit=200,
        )
        return [{"role": m.role, "content": m.content} for m in messages]
