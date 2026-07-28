"""Routing a channel message to the agent it names.

A Slack or Telegram bot is one endpoint standing in front of every agent an
organization has published. Without a way to say *which* one, the bot can only
ever be a single assistant, and every new agent needs its own bot token, its own
webhook and its own place in the workspace's app directory.

``@support what is the refund window`` is that way. The handle is the agent's
slug — the same one the Builder shows and the same one the API takes — so a
person who can see an agent in the UI already knows how to reach it from Slack.

Three rules make this safe to expose in a shared channel:

*The run belongs to a person.* A mention from an unlinked channel identity is
refused rather than run as the bot or as the organization. Budgets, resource
grants and the audit trail all take a subject, and a run with no subject is one
nobody is accountable for.

*The agent has to have been put here.* A handle resolves only among the agents
*exposed* to this bot — see :mod:`app.services.agent_exposure`. It used to
resolve against every published agent in the organization, which made one Slack
app a door onto all of them; nobody decided that, it fell out of resolving the
handle against the org rather than against the bot.

*The mention decides nothing about access.* The slug is resolved inside the
bot's organization and then handed to the registry, which applies the caller's
role and grants exactly as it would for the same request from the web app. A
handle typed into a public channel is a name, not a key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import RunSurface
from app.repositories import agent_exposure_repo, agent_repo, member_repo
from app.services.agent_runner import AgentRunnerService

# Matches a leading handle and keeps everything after it as the prompt. Anchored
# at the start on purpose: a slug appearing mid-sentence is someone talking
# *about* an agent, not to it.
_MENTION = re.compile(r"^\s*@([a-z0-9][a-z0-9-]{0,63})\b[:,]?\s*(.*)$", re.DOTALL)

# Which surface a run is stamped with, so run history can be filtered by where
# it came from. Anything else is recorded as an API run rather than guessed at.
_SURFACES: dict[str, RunSurface] = {
    "slack": RunSurface.SLACK,
    "telegram": RunSurface.TELEGRAM,
}

# Said to anyone whose channel identity has no account behind it. Deliberately
# identical whether they never linked or were removed from the organization —
# both are "we do not know who you are here", and telling them apart would leak
# whether an account exists.
_LINK_FIRST = "Link your account before talking to an agent — send /link to this bot."

# Said when the handle names a real agent that nobody has made available here.
# Deliberately *not* the same answer a typo gets: the bindings are new, so the
# common case for this message is a bot that used to answer and now does not,
# and someone in that position should learn why from the bot rather than from a
# changelog. The trade is that a member learns an agent by that name exists in
# their own organization without being able to reach it — which they can already
# infer from the registry's own refusal, and which is worth less than a channel
# nobody can debug.
_NOT_EXPOSED_HERE = (
    "@{slug} is not available on this bot. Someone who can publish it has to add "
    "this bot under 'Where this agent is available' in the Builder."
)


@dataclass(frozen=True)
class Mention:
    """A message addressed to one agent."""

    slug: str
    prompt: str


def parse_mention(text: str) -> Mention | None:
    """Split ``@handle rest of message`` into its parts, or ``None``.

    Returns ``None`` for a bare handle with nothing after it. ``@support`` alone
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


class ChannelAgentRouter:
    """Answers channel messages that name a published agent."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runner = AgentRunnerService(db)

    async def answer(
        self,
        text: str,
        *,
        platform: str,
        organization_id: UUID,
        bot_id: UUID,
        user_id: UUID | None,
        conversation_id: UUID | None = None,
    ) -> str:
        """Run the agent named in ``text`` and return what it said.

        Args:
            text: The raw incoming message, handle included.
            platform: Which channel it arrived on, for the run's surface.
            organization_id: The bot's organization; the slug is resolved here
                and nowhere else, so one workspace cannot reach another's agents.
            bot_id: The bot the message arrived on. An agent answers through it
                only if an exposure says so — the organization is where the
                handle is *looked up*, not what makes it reachable.
            user_id: The platform user's linked account, or ``None`` if they
                never linked one.
            conversation_id: The channel session's conversation, so a thread
                keeps its history.

        Returns:
            The agent's answer, or an empty string when a tool call was parked
            for approval — the same contract as
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

        answer, _run = await self.runner.execute(
            ctx,
            agent.id,
            mention.prompt,
            surface=_SURFACES.get(platform, RunSurface.API),
            conversation_id=conversation_id,
            # The binding is what let this message through, so it is also what
            # the run is attributed to and bounded by. Resolving it here and
            # then not passing it on would leave a cap somebody set on this bot
            # enforcing nothing.
            exposure=exposure,
        )
        return answer

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
