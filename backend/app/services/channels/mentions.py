"""Routing a channel message to the agent it names.

A Slack or Telegram bot is one endpoint standing in front of every agent an
organization has published. Without a way to say *which* one, the bot can only
ever be a single assistant, and every new agent needs its own bot token, its own
webhook and its own place in the workspace's app directory.

`@support what is the refund window` is that way. The handle is the agent's
slug - the same one the Builder shows and the same one the API takes - so a
person who can see an agent in the UI already knows how to reach it from Slack.
A message that names no handle goes to the bot's only exposed agent, when there
is exactly one; a bot is never anything more than the agents put behind it.

Three rules make this safe to expose in a shared channel:

*The run belongs to a person.* A mention from an unlinked channel identity is
refused rather than run as the bot or as the organization. Budgets, resource
grants and the audit trail all take a subject, and a run with no subject is one
nobody is accountable for.

*The agent has to have been put here.* A handle resolves only among the agents
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

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import RunSurface
from app.db.models.chat_file import ChatFile
from app.db.models.organization import Organization
from app.repositories import agent_exposure_repo, agent_repo, member_repo
from app.services.agent_runner import AgentRunnerService
from app.services.channels.base import OutgoingAttachment
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
# it came from. Anything else is recorded as an API run rather than guessed at.
_SURFACES: dict[str, RunSurface] = {
    "slack": RunSurface.SLACK,
    "telegram": RunSurface.TELEGRAM,
    "mattermost": RunSurface.MATTERMOST,
}

# Said to anyone whose channel identity has no account behind it. Deliberately
# identical whether they never linked or were removed from the organization -
# both are "we do not know who you are here", and telling them apart would leak
# whether an account exists.
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

# Said when a message names no agent and the bot serves several, so answering
# would mean guessing which one was meant. The handles are listed because the
# sender's next message should be able to just start with one.
_SAY_WHICH = (
    "Several agents answer on this bot - start your message with the one you want: {handles}"
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
    """
    match = _MENTION.match(text)
    if match is None:
        return None
    slug, prompt = match.group(1), match.group(2).strip()
    if not prompt:
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


class ChannelAgentRouter:
    """Answers channel messages that name a published agent."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runner = AgentRunnerService(db)
        self.usage = UsageReportService(db)

    @staticmethod
    def _channel_key(platform_chat_id: str) -> str:
        """The chat this message arrived in, with any thread stripped.

        Slack folds `thread_ts` into `platform_chat_id` as `channel:thread_ts`, so
        the raw id identifies a *thread*. A workspace scoped to the channel has to
        key on what is stable across the threads inside it, which is the part
        before the colon. Every other platform's id is already the chat.
        """
        return platform_chat_id.partition(":")[0]

    async def answer(
        self,
        text: str,
        *,
        platform: str,
        organization_id: UUID,
        bot_id: UUID,
        user_id: UUID | None,
        conversation_id: UUID | None = None,
        platform_chat_id: str | None = None,
        usage_reporting: dict[str, Any] | None = None,
        turn: int = 0,
        attachments: list[ChatFile] | None = None,
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
            conversation_id: The channel session's conversation, so a thread
                keeps its history.

        Returns:
            The agent's answer, or an empty string when a tool call was parked
            for approval - the same contract as
            :meth:`AgentRunnerService.execute`.

        Raises:
            UnaddressedMessage: If the message names no agent. This is the
                common case, not an error: the caller decides what an
                unaddressed message means for its bot.
            AuthorizationError: If the sender never linked an account.
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

        ctx = await self._context(organization_id, user_id, slug=mention.slug)
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

        produced: list[OutgoingAttachment] = []
        refused: list[str] = []
        answer, run = await self.runner.execute(
            ctx,
            agent.id,
            mention.prompt,
            attachments=attachments,
            outbound=produced,
            outbound_refused=refused,
            surface=_SURFACES.get(platform, RunSurface.API),
            conversation_id=conversation_id,
            channel_key=(None if platform_chat_id is None else self._channel_key(platform_chat_id)),
            # The binding is what let this message through, so it is also what
            # the run is attributed to and bounded by. Resolving it here and
            # then not passing it on would leave a cap somebody set on this bot
            # enforcing nothing.
            exposure=exposure,
        )
        return AnsweredTurn(
            text=await self._with_usage(
                ctx, answer, run, usage_reporting=usage_reporting, turn=turn
            ),
            attachments=produced,
            refused=refused,
        )

    async def answer_default(
        self,
        text: str,
        *,
        platform: str,
        organization_id: UUID,
        bot_id: UUID,
        user_id: UUID | None,
        conversation_id: UUID | None = None,
        platform_chat_id: str | None = None,
        usage_reporting: dict[str, Any] | None = None,
        turn: int = 0,
        attachments: list[ChatFile] | None = None,
        message_history: list[Any] | None = None,
    ) -> AnsweredTurn:
        """Run the only agent this bot serves and return what it said.

        The unaddressed half of :meth:`answer`: a message naming no handle goes
        to the bot's single active exposure, because someone messaging a bot
        that serves exactly one agent has already said which agent they want.
        With several exposed there is no honest guess - the sender is asked to
        name one - and with none there is nothing to run at all.

        Args:
            text: The whole incoming message; there is no handle to strip.
            message_history: The channel thread so far, in Pydantic AI's format.
                A direct-message bot is a conversation, not a sequence of
                one-shot prompts, and the mention path's statelessness is about
                shared channels, not about this one.

        Raises:
            BadRequestError: If the bot exposes no agent, or more than one.
                Both messages say what to do next, because the person reading
                them is standing in a chat that just refused to answer.
            AuthorizationError: If the sender never linked an account.
            NotFoundError: If the sender may not see the one exposed agent.
        """
        exposed = await agent_exposure_repo.list_active_for_bot(self.db, channel_bot_id=bot_id)
        if not exposed:
            raise BadRequestError(message=_NOTHING_EXPOSED_HERE, details={"bot_id": str(bot_id)})
        if len(exposed) > 1:
            handles = ", ".join(f"@{agent.slug}" for _, agent in exposed)
            raise BadRequestError(
                message=_SAY_WHICH.format(handles=handles),
                details={"bot_id": str(bot_id), "handles": handles},
            )

        exposure, agent = exposed[0]
        ctx = await self._context(organization_id, user_id, slug=agent.slug)
        produced: list[OutgoingAttachment] = []
        refused: list[str] = []
        answer, run = await self.runner.execute(
            ctx,
            agent.id,
            text,
            attachments=attachments,
            outbound=produced,
            outbound_refused=refused,
            surface=_SURFACES.get(platform, RunSurface.API),
            conversation_id=conversation_id,
            channel_key=(None if platform_chat_id is None else self._channel_key(platform_chat_id)),
            message_history=message_history,
            exposure=exposure,
        )
        return AnsweredTurn(
            text=await self._with_usage(
                ctx, answer, run, usage_reporting=usage_reporting, turn=turn
            ),
            attachments=produced,
            refused=refused,
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

    async def _context(
        self, organization_id: UUID, user_id: UUID | None, *, slug: str
    ) -> AuthContext:
        """The sender's authorization context, or a refusal.

        An unlinked identity and a linked one whose account was removed from the
        organization are both refused: in either case there is no membership to
        take a role from, and running with no role would mean running with none
        of the checks a role implies.
        """
        if user_id is None:
            raise AuthorizationError(message=_LINK_FIRST, details={"agent": slug})

        membership = await member_repo.get(
            self.db, organization_id=organization_id, user_id=user_id
        )
        if membership is None:
            raise AuthorizationError(message=_LINK_FIRST, details={"agent": slug})

        return AuthContext(
            user_id=user_id,
            organization_id=organization_id,
            role=membership.role,
        )
