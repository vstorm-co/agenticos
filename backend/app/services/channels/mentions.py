"""Routing a channel message to the agent behind the bot.

**A bot serves exactly one agent** - `uq_exposure_bot` - so most of what this
module does is find that agent and hand it the message. A bot user is one
identity in the chat: on Mattermost every reply arrives from the same avatar
and the same name whichever agent produced it, so several behind one bot meant
somebody in a channel typing a slug to pick between things they could not see,
and a message naming none was answered with a list of handles rather than an
answer. Two agents is two bots, which costs an operator two minutes and makes
the chat say which agent it is talking to.

`@support what is the refund window` still works, and is now an *alias* rather
than a router: the handle is the agent's slug - the same one the Builder shows
and the same one the API takes - and naming an agent that is not the one behind
this bot is refused rather than reaching it.

Three rules make this safe to expose in a shared channel:

*The run belongs to somebody.* A direct message is a conversation with a person,
so an unlinked identity is refused there until it names one. A channel is a room:
the turn runs under the *binding's* creator, the way a hosted page's visitor runs
under the page's owner, and the chat account that typed it is recorded on the run
(#639). What is never true is a run belonging to the bot or to the organization at
large - budgets, resource grants and the audit trail all take a subject, and every
path here has one.

*The agent has to have been put here.* A handle resolves only against the agent
*exposed* to this bot - see :mod:`app.services.agent_exposure`. It used to
resolve against every published agent in the organization, which made one Slack
app a door onto all of them; nobody decided that, it fell out of resolving the
handle against the org rather than against the bot.

*The mention decides nothing about access.* The slug is resolved inside the
bot's organization and then handed to the registry, which applies the caller's
role and grants exactly as it would for the same request from the web app. A
handle typed into a public channel is a name, not a key.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.channel_tools import ChannelDirectory
from app.agents.capabilities.charts._spec import parse_chart_spec
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.memory_keys import room_owner_key
from app.core.permissions import AuthContext
from app.db.models.agent_exposure import AgentExposure
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.chat_file import ChatFile
from app.db.models.organization import Organization
from app.repositories import agent_exposure_repo, agent_repo, member_repo
from app.services.access import publisher_context
from app.services.agent_runner import AgentRunnerService, RunStream
from app.services.channels.base import ROOM_HANDLES, OutgoingAttachment, channel_key
from app.services.channels.chart_png import render_chart_png
from app.services.transcript import RecordedToolCall
from app.services.usage_report import (
    UsageReportService,
    format_footer,
    needs_sandbox_sample,
    should_report,
)

# Matches a leading handle and keeps everything after it as the prompt. Anchored
# at the start on purpose: a slug appearing mid-sentence is someone talking
# *about* an agent, not to it.
_MENTION = re.compile(r"^\s*@([a-z0-9][a-z0-9-]{0,63})\b[:,]?\s*(.*)$", re.DOTALL)

# Which surface a run is stamped with, so run history can be filtered by where
# it came from. Anything else is recorded as an API run rather than guessed at -
# which is why every platform this router serves has to be in here. Mattermost
# was not, so a Mattermost mention was recorded as an HTTP API call: nothing
# errored, the number simply landed in the wrong bucket and every reader of the
# column inherited it (#208).
_SURFACES: dict[str, RunSurface] = {
    "slack": RunSurface.SLACK,
    "telegram": RunSurface.TELEGRAM,
    "mattermost": RunSurface.MATTERMOST,
}


# Said to anyone whose channel identity has no account behind it. Deliberately
# identical whether they never linked or were removed from the organization -
# both are "we do not know who you are here", and telling them apart would leak
# whether an account exists.
def drawn_chart(called: list[RecordedToolCall]) -> bytes | None:
    """The last chart this turn drew, as a PNG, or None if it drew none.

    The *last*, because a turn that draws twice has refined the first attempt and
    a reply carries one image. A result that no longer parses is skipped rather
    than raised on: the payload is whatever the tool returned, and a chart that
    cannot be drawn must not cost somebody the answer it came with.

    Blocking: Pillow rasterises and PNG-encodes here, and a channel turn runs on
    the loop the pollers and the other webhook tasks share - so the callers reach
    it through `asyncio.to_thread`, never inline.
    """
    for call in reversed(called):
        if call.tool_name != _CHART_TOOL or call.result is None:
            continue
        spec = parse_chart_spec(call.result)
        if spec is None:
            continue
        try:
            return render_chart_png(spec)
        except Exception:
            logger.exception("Could not render a chart for a channel reply")
            return None
    return None


_CHART_TOOL = "create_chart"
"""What the charts capability registers. One name, read in one place."""

_LINK_FIRST = "Link your account before talking to an agent - send /link to this bot."

# Said when the handle names a real agent that nobody has made available here.
# Deliberately *not* the same answer a typo gets: the bindings are new, so the
# common case for this message is a bot that used to answer and now does not,
# and someone in that position should learn why from the bot rather than from a
# changelog. The trade is that a member learns an agent by that name exists in
# their own organization without being able to reach it - which they can already
# infer from the registry's own refusal, and which is worth less than a channel
# nobody can debug.
_NOT_EXPOSED_HERE = (
    "@{slug} is not available on this bot. Someone who can publish it has to add "
    "this bot under 'Where this agent is available' in the Builder."
)

# Said when a message names no agent and the bot serves none. There is no
# assistant behind a bot any more - a bot only ever relays to published agents -
# so the fix is the same one _NOT_EXPOSED_HERE points at, phrased for the person
# who can do it.
_NOTHING_EXPOSED_HERE = (
    "No agent is available on this bot yet. Publish an agent and add this bot "
    "under 'Where this agent is available' in the Builder."
)


@dataclass(frozen=True)
class Mention:
    """A message addressed to one agent."""

    slug: str
    prompt: str


def parse_mention(text: str) -> Mention | None:
    """Split `@handle rest of message` into its parts, or `None`.

    Returns `None` for a bare handle with nothing after it. `@support` alone
    is a greeting, and answering it would open a billed run to say hello.

    And `None` for a handle that addresses the *room* - `@channel`, `@all`,
    `@here`, `@everyone`. They match the slug pattern, so a standup announcement
    read as a mention of an agent nobody has, and because a channel-wide mention
    puts every member including the bot in the platform's mention list the bot
    considered itself named and answered under it. Nobody typing `@channel` is
    addressing an agent, which makes this a property of the parser rather than a
    refusal further down.
    """
    match = _MENTION.match(text)
    if match is None:
        return None
    slug, prompt = match.group(1), match.group(2).strip()
    if not prompt or slug in ROOM_HANDLES:
        return None
    return Mention(slug=slug, prompt=prompt)


class UnaddressedMessage(Exception):
    """The message names no agent, so the caller should handle it itself."""


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnsweredTurn:
    """What a channel should send back: words, files, and what would not fit.

    A single string was enough while an agent could only talk. Now that it can
    produce a spreadsheet, the answer and the file it is about have to arrive
    together - a reply that posted them separately would read as two messages
    about different things.
    """

    text: str
    attachments: list[OutgoingAttachment] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    """Produced files the reply names instead of carrying."""

    awaiting_approval_run_id: UUID | None = None
    """The run parked on a decision, when that is how the turn ended.

    Carried so the reply can link to it. "Check the approvals queue" told
    somebody in a chat window to go and find a page they may never have opened,
    on a product they reach through a bot - which is most of the way to not
    telling them at all.
    """

    image_png: bytes | None = None
    """A chart the turn drew, rendered for a surface that cannot run Recharts.

    Beside the attachments rather than among them because a chart is not a file
    somebody asked for: it is the answer, and every adapter posts it as an image
    with the text rather than as something to download.
    """

    status: str = RunStatus.COMPLETED
    """How the run ended, so the reply can tell an empty answer's reasons apart.

    Typed `str` to match `AgentRun.status` (`Mapped[str]`) - the whole codebase
    holds a run status as a string and compares it against the `RunStatus`
    members, which are strings.

    An empty `text` is not one thing: a run parked on an approval, one stopped
    at its budget, and one that simply produced no words all arrive empty, and
    only `awaiting_approval_run_id` distinguished the first - so the other two
    were told "that needs approval", which sends somebody to a runs page over a
    decision that was never raised.
    """


def _memory_room_key(
    platform: str, platform_chat_id: str | None, chat_type: str | None
) -> str | None:
    """The memory store of the room a message arrived in, or `None` for a DM.

    The one place that can answer it: deciding a chat has more than one listener
    needs the platform's own channel type, which stops here - the runner sees only
    a `channel_key`, and a Slack DM has one of those exactly like a channel does.
    Getting it wrong in the permissive direction is what would let a note taken in
    a direct message be read back to a whole channel, so an unknown `chat_type` is
    read as private (#788).

    Keyed on `channel_key`, not the raw id, so a room remembers across its threads
    rather than starting over in each one.
    """
    if platform_chat_id is None or chat_type is None or chat_type == "private":
        return None
    return room_owner_key(platform, channel_key(platform_chat_id))


class ChannelAgentRouter:
    """Answers channel messages that name a published agent."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runner = AgentRunnerService(db)
        self.usage = UsageReportService(db)

    async def answer(
        self,
        text: str,
        *,
        platform: str,
        organization_id: UUID,
        bot_id: UUID,
        user_id: UUID | None,
        channel_identity_id: UUID | None = None,
        admit_unlinked: bool = False,
        conversation_id: UUID | None = None,
        platform_chat_id: str | None = None,
        chat_type: str | None = None,
        channel_directory: ChannelDirectory | None = None,
        turn: int = 0,
        attachments: list[ChatFile] | None = None,
        stream: RunStream | None = None,
        message_history: list[Any] | None = None,
    ) -> AnsweredTurn:
        """Run the agent named in `text` and return what it said.

        Args:
            text: The raw incoming message, handle included.
            platform: Which channel it arrived on, for the run's surface.
            organization_id: The bot's organization; the slug is resolved here
                and nowhere else, so one workspace cannot reach another's agents.
            bot_id: The bot the message arrived on. An agent answers through it
                only if an exposure says so - the organization is where the
                handle is *looked up*, not what makes it reachable.
            user_id: The platform user's linked account, or `None` if they
                never linked one.
            channel_identity_id: The chat account the message arrived from,
                recorded on the run so a channel turn says who asked even when
                nobody has linked an account to it.
            admit_unlinked: Whether a sender with no linked account may run under
                the binding's creator instead of being refused. True in a room,
                false in a private conversation - the caller decides, because
                only the caller knows which this is.
            conversation_id: The channel session's conversation, so a thread
                keeps its history.
            channel_directory: This channel, ready to be asked about, for an
                agent whose spec binds `channel_tools`. Bound by the caller
                because it holds the bot's token, and passed through unread:
                a run with none simply gets no channel tools.

        How talkative the reply is about what a turn cost is not a parameter:
        it is the binding's, read off the exposure this method has just
        resolved. It used to arrive from the router as the *bot's* setting,
        which made it the operator's rather than the agent author's - and once
        a bot served one agent there was nothing left for two copies to say.

        Returns:
            The agent's answer, or an empty string when a tool call was parked
            for approval - the same contract as
            :meth:`AgentRunnerService.execute`.

        Raises:
            UnaddressedMessage: If the message names no agent. This is the
                common case, not an error: the caller decides what an
                unaddressed message means for its bot.
            AuthorizationError: If the sender has no account and this is not a
                room.
            NotFoundError: If no agent in this organization holds that handle,
                or the sender may not see the one that does. Both answer with
                the same message, so a channel cannot be used to enumerate the
                agents someone is not entitled to.
            BadRequestError: If the agent exists but is not exposed on this bot.
                Its own message, because "nobody put it here" has a fix and
                "that handle does not exist" does not.
        """
        mention = parse_mention(text)
        if mention is None:
            raise UnaddressedMessage

        sender = await self._membership_context(
            organization_id,
            user_id,
            slug=mention.slug,
            channel_identity_id=channel_identity_id,
            admit_unlinked=admit_unlinked,
        )

        agent = await agent_repo.get_by_slug(self.db, mention.slug, organization_id=organization_id)
        if agent is None:
            raise NotFoundError(
                message=f"No agent here answers to @{mention.slug}.",
                details={"slug": mention.slug},
            )

        exposure = await agent_exposure_repo.get_for_bot(
            self.db, agent_id=agent.id, channel_bot_id=bot_id
        )
        if exposure is None or not exposure.is_active:
            # A paused binding and no binding say the same thing to a person in
            # the channel: it is not available here, and someone has to change
            # that in the Builder. Distinguishing them would only tell them which
            # screen the switch is on.
            raise BadRequestError(
                message=_NOT_EXPOSED_HERE.format(slug=mention.slug),
                details={"slug": mention.slug, "agent_id": str(agent.id)},
            )

        ctx = sender or await self._binding_context(
            exposure, channel_identity_id=channel_identity_id
        )

        produced: list[OutgoingAttachment] = []
        refused: list[str] = []
        called: list[RecordedToolCall] = []
        answer, run = await self.runner.execute(
            ctx,
            agent.id,
            mention.prompt,
            attachments=attachments,
            outbound=produced,
            outbound_refused=refused,
            tool_calls=called,
            stream=stream,
            surface=_SURFACES.get(platform, RunSurface.API),
            conversation_id=conversation_id,
            channel_key=(None if platform_chat_id is None else channel_key(platform_chat_id)),
            memory_room_key=_memory_room_key(platform, platform_chat_id, chat_type),
            channel_directory=channel_directory,
            # The thread this agent was brought into, where the router read one.
            # Without it a named agent answered an existing thread as though it
            # were empty, because only the default path prepended the backfill.
            message_history=message_history,
            # The same rule as the default path: a mention from a member speaks
            # through that person's own MCP accounts, and the room reads the
            # answer exactly as it reads the question. `sender`, not `user_id`,
            # for the same reason - a former member's turn runs under the
            # publisher, whose accounts must not be reached for.
            acts_for_sender=sender is not None,
            # The binding is what let this message through, so it is also what
            # the run is attributed to and bounded by. Resolving it here and
            # then not passing it on would leave a cap somebody set on this bot
            # enforcing nothing.
            exposure=exposure,
        )
        return AnsweredTurn(
            text=await self._with_usage(
                ctx, answer, run, usage_reporting=exposure.usage_reporting, turn=turn
            ),
            attachments=produced,
            refused=refused,
            image_png=await asyncio.to_thread(drawn_chart, called),
            awaiting_approval_run_id=(
                run.id if run.status == RunStatus.AWAITING_APPROVAL else None
            ),
            status=run.status,
        )

    async def answer_default(
        self,
        text: str,
        *,
        platform: str,
        organization_id: UUID,
        bot_id: UUID,
        user_id: UUID | None,
        channel_identity_id: UUID | None = None,
        admit_unlinked: bool = False,
        conversation_id: UUID | None = None,
        platform_chat_id: str | None = None,
        chat_type: str | None = None,
        channel_directory: ChannelDirectory | None = None,
        turn: int = 0,
        attachments: list[ChatFile] | None = None,
        message_history: list[Any] | None = None,
        stream: RunStream | None = None,
    ) -> AnsweredTurn:
        """Run the only agent this bot serves and return what it said.

        The unaddressed half of :meth:`answer`, and the ordinary one: a bot
        serves exactly one agent - `uq_exposure_bot` - so a message that names
        no handle has already said which agent it is for. The only other state
        is a bot nobody has bound anything to, and there is nothing to run.

        Args:
            text: The whole incoming message; there is no handle to strip.
            message_history: The channel thread so far, in Pydantic AI's format.
                A direct-message bot is a conversation, not a sequence of
                one-shot prompts, and the mention path's statelessness is about
                shared channels, not about this one.

        Raises:
            BadRequestError: If the bot exposes no agent. The message says what
                to do next, because the person reading it is standing in a chat
                that just refused to answer.
            AuthorizationError: If the sender has no account and this is not a
                room.
            NotFoundError: If the sender may not see the one exposed agent.
        """
        exposed = await agent_exposure_repo.list_active_for_bot(self.db, channel_bot_id=bot_id)
        if not exposed:
            raise BadRequestError(message=_NOTHING_EXPOSED_HERE, details={"bot_id": str(bot_id)})

        # At most one, guaranteed by the unique constraint on the bot. This used
        # to be a list to choose from, and choosing was the sender's problem:
        # a message naming no handle was answered with a list of slugs instead
        # of an answer, for agents they could not see.
        exposure, agent = exposed[0]
        sender = await self._membership_context(
            organization_id,
            user_id,
            slug=agent.slug,
            channel_identity_id=channel_identity_id,
            admit_unlinked=admit_unlinked,
        )
        ctx = sender or await self._binding_context(
            exposure, channel_identity_id=channel_identity_id
        )
        produced: list[OutgoingAttachment] = []
        refused: list[str] = []
        called: list[RecordedToolCall] = []
        answer, run = await self.runner.execute(
            ctx,
            agent.id,
            text,
            attachments=attachments,
            outbound=produced,
            outbound_refused=refused,
            tool_calls=called,
            stream=stream,
            surface=_SURFACES.get(platform, RunSurface.API),
            conversation_id=conversation_id,
            channel_key=(None if platform_chat_id is None else channel_key(platform_chat_id)),
            memory_room_key=_memory_room_key(platform, platform_chat_id, chat_type),
            channel_directory=channel_directory,
            # A sender who is a member speaks through their own MCP accounts, in
            # a room as much as in a direct message: the account is this
            # message's author, never the thread's. `sender`, not `user_id`: a
            # linked account whose person has left the organization runs under
            # the binding's publisher, and the publisher's accounts are not the
            # room's to use.
            acts_for_sender=sender is not None,
            message_history=message_history,
            exposure=exposure,
        )
        return AnsweredTurn(
            text=await self._with_usage(
                ctx, answer, run, usage_reporting=exposure.usage_reporting, turn=turn
            ),
            attachments=produced,
            refused=refused,
            image_png=await asyncio.to_thread(drawn_chart, called),
            awaiting_approval_run_id=(
                run.id if run.status == RunStatus.AWAITING_APPROVAL else None
            ),
            status=run.status,
        )

    async def _with_usage(
        self,
        ctx: AuthContext,
        answer: str,
        run: Any,
        *,
        usage_reporting: dict[str, Any] | None,
        turn: int,
    ) -> str:
        """The answer, with what the turn cost under it when the bot says so.

        Recorded whichever way the bot is configured, and only *spoken* when its
        mode says to. "The bot went quiet" is a question somebody asks days later,
        and a report that was never written is no help then.

        An empty answer is left empty. That is the parked-approval contract - the
        caller turns it into "this needs approval" - and appending an accounting
        line to nothing would make a footer look like the reply.

        Never raises. This hangs off an answer somebody is waiting for; a
        workspace that cannot be measured must not turn a good turn into an error.
        """
        try:
            report = await self.usage.for_run(
                ctx,
                run,
                period_spend_usd=await self.runner.monthly_spend(ctx),
                budget_usd=await self._budget(ctx),
                include_sandbox=needs_sandbox_sample(usage_reporting),
            )
        except Exception:
            logger.warning("usage_report_failed", extra={"run_id": str(run.id)}, exc_info=True)
            return answer

        line = format_footer(report)
        logger.info("channel_turn_usage", extra={"run_id": str(run.id), "usage": line})
        if not answer or not should_report(usage_reporting, report, turn=turn):
            return answer
        return f"{answer}\n\n_{line}_"

    async def _budget(self, ctx: AuthContext) -> Decimal | None:
        """This organization's monthly cap, or `None` if it set none.

        The organization's rather than the agent's: an agent's cap is its author's
        to raise, while this one stops every agent at once - which is the one worth
        warning a channel about before it happens.
        """
        organization = await self.db.get(Organization, ctx.organization_id)
        return None if organization is None else organization.monthly_budget_usd

    async def _membership_context(
        self,
        organization_id: UUID,
        user_id: UUID | None,
        *,
        slug: str,
        channel_identity_id: UUID | None,
        admit_unlinked: bool,
    ) -> AuthContext | None:
        """The sender's own context, `None` if the turn runs under the binding.

        Split from :meth:`_binding_context` so that *whether this sender may be
        answered at all* is decided before anything is looked up. A sender who
        may not must not learn from the refusal whether the handle they typed
        exists - which is the property the mention path is built on, and one only
        this ordering keeps.

        A linked sender who is still a member runs as themselves: their role,
        their grants, their name on the audit entry.

        `admit_unlinked` is the caller's answer to whether this is a room or a
        private conversation - a group chat, unless the bot's policy asks for a
        link. Where it holds, a sender this platform cannot name runs under the
        binding instead; where it does not, they are refused, which is every
        direct message.

        A linked account that is no longer a member takes the same path as an
        unlinked one rather than a third: there is no membership to read a role
        from, and in a room a former member is no more entitled than the stranger
        beside them. A deactivated account is one of those, which is why this is
        the joined read: the membership row outlives a deactivation, and the link
        in `channel_identities` outlives it too, so the plain read ran an
        offboarded Owner's turns at their full authority from a chat account
        nobody had unlinked - refused everywhere they sign in, except here.
        """
        if user_id is not None:
            membership = await member_repo.get_active(
                self.db, organization_id=organization_id, user_id=user_id
            )
            if membership is not None:
                return AuthContext(
                    user_id=user_id,
                    organization_id=organization_id,
                    role=membership.role,
                    channel_identity_id=channel_identity_id,
                )

        if not admit_unlinked:
            raise AuthorizationError(message=_LINK_FIRST, details={"agent": slug})

        return None

    async def _binding_context(
        self, exposure: AgentExposure, *, channel_identity_id: UUID | None
    ) -> AuthContext:
        """The context a turn nobody can name runs under: the binding creator's.

        One line, because the rule and its `viewer` fallback are the same ones a
        widget and a hosted page answer with - see `access.publisher_context`, which
        is where the reasoning now lives so the two cannot drift apart (#640).
        """
        return await publisher_context(
            self.db,
            organization_id=exposure.organization_id,
            publisher_user_id=exposure.created_by_user_id,
            channel_identity_id=channel_identity_id,
        )
