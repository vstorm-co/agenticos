"""Channel message router - processes incoming messages end-to-end."""

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.core.exceptions import AppException, AuthorizationError, BadRequestError
from app.db.models.agent_run import RunStatus
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
from app.services.channels.base import (
    IncomingMessage,
    OutgoingAttachment,
    OutgoingMessage,
    channel_key,
)
from app.services.channels.dedupe import claim_delivery, release_delivery
from app.services.channels.directory import BoundChannelDirectory
from app.services.channels.live_reply import WORKING, LiveReply, channel_stream
from app.services.channels.mentions import (
    ChannelAgentRouter,
    UnaddressedMessage,
    parse_mention,
)

logger = logging.getLogger(__name__)

# key format: "{bot_id}:{identity_id}", value = (count, window_start_ts)
_rate_buckets: dict[str, tuple[int, float]] = {}

_DEFAULT_RPM = 10

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


# How much of a channel thread the model is reminded of.
#
# Its own number rather than the widget's 40, and larger, because the two surfaces
# are bounded for different reasons. A widget's is a public URL with somebody
# else's budget behind it, so the ceiling is about spend. A channel is a room the
# operator's own colleagues work in: the thread is long-lived and shared, so a
# window that only holds a few turns loses context two people are relying on. What
# it is still bounded *for* is the same - a prompt is not a transcript, and one
# thread's whole history is a per-turn bill that grows for ever.
HISTORY_MESSAGES = 200


def _get_chat_lock(bot_id: str, chat_id: str) -> asyncio.Lock:
    """Return (or create) the asyncio.Lock for a bot + chat pair."""
    key = f"{bot_id}:{chat_id}"
    if key not in _chat_locks:
        _chat_locks[key] = asyncio.Lock()
    return _chat_locks[key]


def _needs_approval(run_id: Any) -> str:
    """What to say when the turn parked on a decision instead of answering.

    With the run's own address in it. "Check the approvals queue" asks somebody
    sitting in a chat window to go and find a page they may never have opened, in
    a product they reach through a bot - which is most of the way to not telling
    them at all. `?run=` is the same link a delegation panel hands over with, so
    it lands on the decision rather than on a list to search.
    """
    where = f"{settings.FRONTEND_URL.rstrip('/')}/runs"
    if run_id is not None:
        return f"That needs approval before it can run: {where}?run={run_id}"
    return f"That needs approval before it can run - decide it here: {where}"


def _empty_answer(answered: Any) -> str:
    """What to say when a turn ended with no words, told apart by why.

    An empty answer used to always read as "that needs approval", but the three
    reasons a turn ends empty are not the same message. A run parked on an
    approval links to the decision; one stopped at its budget says the assistant
    is at its ceiling; anything else - a crash caught upstream, a model that
    produced no text - gets a plain apology rather than being sent to a runs
    page over a decision that was never raised.
    """
    if answered.awaiting_approval_run_id is not None:
        return _needs_approval(answered.awaiting_approval_run_id)
    if answered.status == RunStatus.BUDGET_EXCEEDED:
        return "This assistant has reached its usage limit."
    return "Sorry, I could not produce an answer to that. Please try again."


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
        """Claim the delivery, acquire the per-chat lock, then process.

        The claim comes first, and before the lock on purpose: a redelivered
        message (a platform retries when its 2xx is lost) would otherwise
        queue behind the run it duplicates and then answer again - the lock
        converts the race into an orderly double answer, it never prevents
        one (#167). The lock then ensures concurrent messages in the same
        group chat are processed sequentially - no duplicate sessions, no
        interleaved agent calls.

        A run that does not finish gives the claim back, so the redelivery that
        follows it is answered rather than mistaken for a duplicate. Cancellation
        counts, which is why the handler is `BaseException`: a pod draining
        mid-run is the case the claim would otherwise outlive.
        """
        if not await claim_delivery(incoming):
            logger.info(
                "Duplicate channel delivery ignored: bot=%s platform=%s message=%s",
                incoming.bot_id,
                incoming.platform,
                incoming.message_id,
            )
            return
        lock = _get_chat_lock(incoming.bot_id, incoming.platform_chat_id)
        try:
            async with lock:
                await self._route_inner(incoming, db)
        except BaseException:
            await release_delivery(incoming)
            raise

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

        if self._is_overheard(incoming):
            # Decided before anything is created or refused, not after. A bot in a
            # channel hears every post, so a refusal - a whitelist that does not
            # list the speaker, a jwt bot they have not linked to - posted before
            # this check talked over two colleagues, message after message, for
            # exactly the policies meant to narrow access; and an identity row was
            # minted for every bystander the bot would never answer. A message
            # naming a handle is not overheard even here - whether that handle is
            # ours is `_answer_mention`'s to judge, and its refusal stays its own.
            logger.debug(
                "channel_message_not_addressed",
                extra={"platform": incoming.platform, "bot_id": incoming.bot_id},
            )
            return

        try:
            self._check_access(incoming, bot)
        except AuthorizationError as exc:
            await self._refuse_if_named(bot, incoming, exc.message)
            return

        command_reply = await self._handle_command(incoming.text, incoming, bot, db)
        if command_reply is not None:
            await self._send_reply(bot, incoming, command_reply)
            return

        try:
            identity = await self._resolve_identity(incoming, bot, db)
        except AuthorizationError as exc:
            await self._refuse_if_named(bot, incoming, exc.message)
            return

        admit_unlinked = self._admits_unlinked(incoming, bot)
        if identity.user_id is None and not admit_unlinked:
            await self._send_reply(bot, incoming, await self._invite_to_link(incoming, db))
            return

        session = await self._resolve_session(incoming, bot, identity, db)

        try:
            self._check_rate_limit(bot, str(identity.id))
        except BadRequestError as exc:
            await self._send_reply(bot, incoming, exc.message)
            return

        # Built here, once, from the row that admitted the message - so an agent
        # that asks about the channel asks about *this* channel, with the bot's
        # own token, and never about one named by the model. Free to build for a
        # turn that never uses it: nothing here calls the platform until a tool
        # does.
        directory = self._channel_directory(bot, incoming)

        # Once, above both paths. A mention that turns out to name nobody of ours
        # falls through to the default assistant, and fetching per path downloaded
        # the same attachment twice and left the first copy stored with nothing
        # pointing at it (#683).
        files, file_refusals = await self._receive_files(db, bot, incoming, identity)

        # The mention path opens its own placeholder lazily, because it may find
        # the handle names a colleague rather than an agent of ours and stay
        # silent - a "…" posted up front would be left hanging under two people's
        # conversation. The default path always answers when it is reached, so it
        # opens eagerly below: the "…" that tells a channel the bot is working
        # rather than crashed.
        if await self._answer_mention(
            incoming,
            bot,
            identity,
            session,
            db,
            directory,
            admit_unlinked,
            files=files,
            file_refusals=file_refusals,
        ):
            return

        live, handle = await self._open_reply(bot, incoming)

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
                channel_identity_id=identity.id,
                admit_unlinked=admit_unlinked,
                conversation_id=session.conversation_id,
                platform_chat_id=incoming.platform_chat_id,
                channel_directory=directory,
                # How many turns this chat has had. `every_n` counts per chat,
                # because "every tenth message" is a question about this
                # conversation and not about whichever channel happened to be
                # tenth across the bot. *Whether* to say anything is the
                # binding's, and the binding is resolved a layer down.
                turn=session.turn_count,
                attachments=files,
                message_history=build_message_history(history),
                stream=None if live is None else channel_stream(live),
            )
        except AppException as exc:
            # A refusal - no agent exposed, several to choose from, an unlinked
            # sender - is the platform answering, not a crash. The message says
            # what to do next.
            await self._discard_files(db, files)
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
        await self._deliver(bot, incoming, answer, answered, handle)

    async def _deliver(
        self,
        bot: Any,
        incoming: IncomingMessage,
        answer: str,
        answered: Any,
        handle: str | None,
    ) -> None:
        """Finish the turn in the message the person has been watching.

        A live reply is already on screen, so the answer replaces it rather than
        arriving underneath it - two messages saying the same thing is worse than
        the silence this replaced. A chart or a produced file still needs a
        second post: no platform lets a message gain an attachment by being
        edited.
        """
        text = answer or _empty_answer(answered)
        if handle is not None:
            adapter = get_adapter(incoming.platform)
            try:
                await adapter.update_reply(
                    unseal_bot_token(bot),
                    OutgoingMessage(
                        platform_chat_id=incoming.platform_chat_id,
                        text=text,
                        api_base_url=getattr(bot, "api_base_url", None),
                    ),
                    handle,
                )
            except Exception:
                # The edit failed - a rate-limit on the last one, or the
                # placeholder was deleted so the PATCH 404s. Fall through to
                # `_send_reply` with the whole answer rather than blanking `text`
                # and posting nothing: `live_reply` promises the answer arrives
                # whole at the end whatever happened.
                logger.warning(
                    "live reply final edit failed; re-posting the answer whole", exc_info=True
                )
            else:
                if answered.image_png is None and not answered.attachments:
                    return
                text = ""

        await self._send_reply(
            bot,
            incoming,
            text,
            answered.attachments,
            image_png=answered.image_png,
        )

    async def _answer_mention(
        self,
        incoming: IncomingMessage,
        bot: Any,
        identity: Any,
        session: Any,
        db: Any,
        directory: BoundChannelDirectory | None,
        admit_unlinked: bool,
        *,
        files: list[Any],
        file_refusals: list[str],
    ) -> bool:
        """Answer `@handle …` with that agent, and report whether we did.

        Placed after the session is resolved so a mentioned agent shares the
        thread's conversation, and before the bot's own assistant so a named
        agent always wins: someone who typed a handle asked for that agent, and
        silently answering as something else is worse than not answering.

        A refusal - an unnamed sender in a private chat, an unknown handle, an
        agent they cannot see, an agent nobody exposed on this bot - is reported
        to the sender and still counts as handled. Falling through to the default
        assistant would answer a question that was not asked.

        The placeholder is opened lazily: a handle that names a colleague rather
        than an agent of ours raises before a token is streamed, so nothing is
        ever posted and no "…" is left hanging under two people's conversation.

        `files` arrive already fetched, because both paths need the same ones and
        this one runs first: receiving them here as well downloaded and stored
        every attachment on an unaddressed message twice, and only the second row
        was ever linked to the turn (#683).
        """
        live, handle_of = self._lazy_reply(bot, incoming)
        try:
            answered = await ChannelAgentRouter(db).answer(
                incoming.text,
                platform=incoming.platform,
                organization_id=bot.organization_id,
                bot_id=bot.id,
                user_id=identity.user_id,
                channel_identity_id=identity.id,
                admit_unlinked=admit_unlinked,
                conversation_id=session.conversation_id,
                platform_chat_id=incoming.platform_chat_id,
                channel_directory=directory,
                turn=session.turn_count,
                attachments=files,
                stream=channel_stream(live),
            )
        except UnaddressedMessage:
            return False
        except AppException as exc:
            # Whether or not the refusal is worth posting, the files this turn
            # already stored are not: a turn that produced no run leaves rows
            # nothing points at, and `chat_files` carries no organization, so an
            # unlinked row is scoped by `user_id` alone (#690).
            await self._discard_files(db, files)
            # A handle that names no agent of ours. In a channel where the bot was
            # not among the mentioned accounts, that handle was somebody's
            # colleague - so the refusal is logged rather than posted, because a bot
            # that answers "@ada is not available on this bot" every time two people
            # talk to each other is the interruption this gate exists to stop. It
            # still counts as handled: nothing else should answer it either. Nothing
            # streamed, so the lazy placeholder was never opened.
            if self._names_the_bot(incoming):
                await self._send_reply(bot, incoming, exc.message)
            else:
                logger.info(
                    "channel_mention_not_ours",
                    extra={"platform": incoming.platform, "bot_id": incoming.bot_id},
                )
            return True

        answer = self._with_notes(answered.text, file_refusals, _kept_back(answered.refused))
        await self._deliver(bot, incoming, answer, answered, handle_of())
        return True

    def _lazy_reply(
        self, bot: Any, incoming: IncomingMessage
    ) -> tuple[LiveReply, Callable[[], str | None]]:
        """A live reply that posts its placeholder on the first push, not before.

        `_open_reply` puts a "…" on screen for every message it is called on. The
        mention path cannot use that: `answer()` may discover the handle names a
        colleague rather than an agent of ours and raise before a token is
        streamed, and a placeholder already posted would be left hanging under
        two people's conversation for ever. Opened on the first push instead,
        nothing appears unless the agent produced something - and a handle that
        resolves to nobody produces nothing.

        The handle is captured so `_deliver` can edit the message into the final
        answer; when nothing streamed it stays `None` and `_deliver` posts the
        answer whole, the same fallback a platform that cannot edit already takes.
        """
        adapter = get_adapter(incoming.platform)
        token = unseal_bot_token(bot)
        state: dict[str, str | None] = {"handle": None}
        opened = False

        async def push(text: str) -> None:
            nonlocal opened
            if not opened:
                opened = True
                placeholder = OutgoingMessage(
                    platform_chat_id=incoming.platform_chat_id,
                    text=text or WORKING,
                    reply_to_message_id=incoming.message_id,
                    api_base_url=getattr(bot, "api_base_url", None),
                )
                try:
                    state["handle"] = await adapter.begin_reply(token, placeholder)
                except Exception:
                    logger.warning(
                        "Could not open a live reply on %s", incoming.platform, exc_info=True
                    )
                return
            if state["handle"] is None:
                return
            await adapter.update_reply(
                token,
                OutgoingMessage(
                    platform_chat_id=incoming.platform_chat_id,
                    text=text,
                    api_base_url=getattr(bot, "api_base_url", None),
                ),
                state["handle"],
            )

        return LiveReply(push), lambda: state["handle"]

    @staticmethod
    def _channel_directory(bot: Any, incoming: IncomingMessage) -> BoundChannelDirectory | None:
        """This channel, bound so an agent can ask about it - or `None`.

        Keyed on `channel_key`, not on `platform_chat_id`: in a thread the raw id
        is `channel:root`, and asking Mattermost about a post id gets a 404 for
        every question. The channel is the thing an agent asks about; the thread
        is where it is answering.

        `None` when the platform has no adapter registered, which is not a state
        an inbound message can reach - the adapter is what parsed it - but is one
        a test or a half-configured deployment can. Refusing the whole turn over
        a capability the agent probably does not have would be the wrong trade.
        """
        try:
            adapter = get_adapter(incoming.platform)
        except KeyError:
            logger.warning("No adapter for %s; channel lookup unavailable", incoming.platform)
            return None
        return BoundChannelDirectory(
            adapter=adapter,
            bot_token=unseal_bot_token(bot),
            channel_id=channel_key(incoming.platform_chat_id),
            api_base_url=getattr(bot, "api_base_url", None),
        )

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
    async def _discard_files(db: Any, files: list[Any]) -> None:
        """Give back what the turn stored, for a turn that was refused.

        The files are fetched and stored before the agent is resolved, so a
        refusal raised in its place - nothing exposed on this bot, a sender whose
        account is nobody's - leaves rows nothing will ever link to a message and
        bytes nothing will ever read (#661). The refusal is still what the sender
        gets: nothing here is allowed to raise in its way.
        """
        if not files:
            return
        await ChannelAttachmentService(db).discard(files)

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

    def _admits_unlinked(self, incoming: IncomingMessage, bot: Any) -> bool:
        """Whether somebody with no linked account may be answered here.

        In a room, yes. Somebody with the rights to invite the bot put it in a
        channel, and the people in that channel are the audience that invitation
        chose - so the turn runs under the binding's creator and the chat account
        is recorded on the run. Requiring each of them to open a direct message
        and click a link first made a channel a dead end: the refusal cannot
        carry the link, because the link is a bearer credential and everybody in
        the channel can read it (#639).

        In a direct message, no. It is a conversation with one person, the link
        is safe to send, and the account it connects is the point of it.

        `require_link` is the way back to refusing both, and this is what makes
        it mean anything: it sat in the default policy, the schema, the CLI and
        the dashboard while the gate it was meant to control refused everybody
        regardless.
        """
        if incoming.chat_type == "private":
            return False
        return not bool(self._parse_policy(bot).get("require_link", False))

    @staticmethod
    def _is_overheard(incoming: IncomingMessage) -> bool:
        """Whether this message was said *near* the bot rather than to it.

                **A direct message is always to the bot** - there is nobody else in the
                room, so requiring a mention there would be asking somebody to address the
                only participant. In a channel it is the other way round: the bot is one
                member of many, and a message that names nobody names nobody.

                The distinction is what was missing. Mattermost's socket delivers every
                post in every channel the bot belongs to, so the default agent answered all
                of them - a bot added to a team channel replied to colleagues talking to
                each other (agenticos#634).

                `addressed is None` means the platform did not say, and that is deliberately
                *not* treated as unaddressed: Slack and Telegram deliver on their own
                subscription rules, and reading silence as "ignore" would make a working bot
                on either go quiet.

        **An `@agent-slug` handle counts as addressing the bot**, and it has to be read
                here rather than left to `_answer_mention`: an agent's slug is a name in *this*
                product, not an account on the platform, so it never appears in a mention list
                and a gate that only trusted that list would have silently broken every
                `@sales what is the refund window` in a channel.

                Read syntactically, which lets a message naming a *colleague* past this gate -
                `@ada` is a handle as far as the pattern is concerned. What stops the bot
                answering that is `_answer_mention` keeping its refusal to itself when the
                platform says the bot was not among the mentioned; see `_names_the_bot`.
        """
        if incoming.chat_type == "private" or incoming.addressed is not False:
            return False
        return parse_mention(incoming.text) is None

    @staticmethod
    def _names_the_bot(incoming: IncomingMessage) -> bool:
        """Whether the bot itself was addressed, as far as the platform will say.

        True in a direct message and true where the platform did not report mentions
        at all, both for the reason `_is_overheard` gives: neither is a case where
        silence is what somebody asked for.
        """
        return incoming.chat_type == "private" or incoming.addressed is not False

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
                _rate_buckets[key] = (1, now)
        else:
            _rate_buckets[key] = (1, now)

    async def _open_reply(
        self, bot: Any, incoming: IncomingMessage
    ) -> tuple[LiveReply | None, str | None]:
        """Put a message on screen now, and return how to keep writing it.

        This is the difference between a bot that is thinking and a bot that has
        crashed, and from the outside those looked identical: a channel bot
        posted one finished message and nothing before it, so a question that
        took twelve seconds and three tool calls bought twelve seconds of
        silence.

        `(None, None)` when the platform cannot edit what it has sent, or when
        posting the placeholder failed. Both mean the same thing to the caller -
        answer the way we always did - which is why a failure here is logged and
        swallowed rather than costing somebody their answer.
        """
        adapter = get_adapter(incoming.platform)
        token = unseal_bot_token(bot)
        placeholder = OutgoingMessage(
            platform_chat_id=incoming.platform_chat_id,
            text=WORKING,
            reply_to_message_id=incoming.message_id,
            api_base_url=getattr(bot, "api_base_url", None),
        )
        try:
            handle = await adapter.begin_reply(token, placeholder)
        except Exception:
            logger.warning("Could not open a live reply on %s", incoming.platform, exc_info=True)
            return None, None
        if handle is None:
            return None, None

        await adapter.typing(str(bot.id), placeholder)

        async def push(text: str) -> None:
            await adapter.update_reply(
                token,
                OutgoingMessage(
                    platform_chat_id=incoming.platform_chat_id,
                    text=text,
                    api_base_url=getattr(bot, "api_base_url", None),
                ),
                handle,
            )

        return LiveReply(push), handle

    async def _refuse_if_named(self, bot: Any, incoming: IncomingMessage, message: str) -> None:
        """Post a refusal only where the bot was actually addressed.

        In a channel the bot is one member of many, so a refusal to a message
        that named it belongs on screen - but a refusal to a message that named a
        colleague, or named nobody, is the interruption the overheard gate exists
        to stop, arriving through the refusal rather than the answer.
        `_answer_mention` already keeps its unknown-handle refusal to itself for
        this reason; an access or identity refusal takes the same rule.
        """
        if self._names_the_bot(incoming):
            await self._send_reply(bot, incoming, message)
        else:
            logger.info(
                "channel_refusal_not_addressed",
                extra={"platform": incoming.platform, "bot_id": incoming.bot_id},
            )

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
        """The most recent turns of the channel thread, oldest first.

        **The most recent, which took a `count` to get right** - and the count
        lives in `conversation_repo.get_recent_messages` now, with the two bugs
        that paid for it. A support channel passes 200 turns in days, because
        `channel_sessions` keys the conversation to the chat and the thread never
        rolls over; past that the bot answered plausibly from a version of the
        conversation that had stopped hundreds of turns ago (#638).
        """
        messages = await conversation_repo.get_recent_messages(
            db, conversation_id, limit=HISTORY_MESSAGES
        )
        return [{"role": m.role, "content": m.content} for m in messages]
