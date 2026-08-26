"""Connecting a chat account to the person behind it.

A run started from a channel belongs to somebody: the budget it spends, what it
may read and the audit entry it writes are all theirs. A message arrives carrying
a platform user id and nothing else, and only a browser session can say who that
is - so the bot mints a request, answers with a URL, and the person who opens it
confirms while already signed in.

The direction matters, and it is the second one tried. A code minted in the
dashboard and typed at the bot asks somebody to copy a string between two
applications, and on Mattermost the command carrying it never arrived at all -
Mattermost parses a leading `/` itself and answers "command with a trigger of
'/link' not found". Clicking a link needs neither.

Before either existed, `/link` could not succeed on any platform: nothing ever
wrote `channel_identities.link_code`, so every identity kept `user_id = NULL` and
every channel refused every message with "Link your account first" (#10).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import AuthContext, Perm
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_link_request import ChannelLinkRequest
from app.repositories import (
    agent_exposure_repo,
    channel_identity_repo,
    channel_link_request_repo,
    channel_session_repo,
    member_repo,
)
from app.schemas.channel_bot import LinkedAgent, LinkedPlace
from app.services.access import AGENT, resolve_access
from app.services.channels.base import IncomingMessage

REQUEST_TTL = timedelta(minutes=15)
"""How long a link URL lives.

It is a bearer credential: whoever opens it claims that chat account. Fifteen
minutes is long enough to switch to a browser and sign in if you were signed out,
and short enough that a URL left in a chat history is not a way in.
"""


def _host_of(api_base_url: str | None) -> str | None:
    """The hostname a self-hosted bot lives on, or `None`.

    The hostname alone, never the configured URL. That value is an operator's:
    it may carry a port, a path, or - on a deployment behind a proxy - basic
    credentials, and none of that is something a profile page needs to render.
    `None` for anything that does not parse as a URL with a host, because a
    half-typed address rendered under an account name reads as the address.
    """
    if not api_base_url:
        return None
    return urlparse(api_base_url).hostname


class ChannelLinkService:
    """Mint a claim on a chat account, and let a signed-in person confirm it."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def request(self, incoming: IncomingMessage) -> str:
        """Mint a request for this sender and return the URL to send them.

        Any request this chat account already has is dropped first, so a URL that
        scrolled out of view stops working rather than lingering.

        `delete_for_identity` then `create` is check-then-act across sessions:
        two near-simultaneous first messages from the same account both delete
        (neither sees the other's uncommitted row) and both insert the same
        `(platform, platform_user_id)`, and the loser hits
        `channel_link_requests_identity_key`. The insert runs inside a savepoint
        so the conflict rolls back that one statement rather than poisoning the
        session, and the request the winner committed is re-read and returned -
        the unlinked-first-message path does not catch this, so left to
        propagate it would answer a bot with a 500 and the sender with silence.
        """
        await channel_link_request_repo.delete_for_identity(
            self.db,
            platform=incoming.platform,
            platform_user_id=incoming.platform_user_id,
        )
        try:
            async with self.db.begin_nested():
                request = await channel_link_request_repo.create(
                    self.db,
                    token=secrets.token_urlsafe(32),
                    platform=incoming.platform,
                    platform_user_id=incoming.platform_user_id,
                    platform_username=incoming.platform_username,
                    platform_display_name=incoming.platform_display_name,
                    expires_at=datetime.now(UTC) + REQUEST_TTL,
                )
        except IntegrityError:
            request = await channel_link_request_repo.get_for_identity(
                self.db,
                platform=incoming.platform,
                platform_user_id=incoming.platform_user_id,
            )
            if request is None:
                raise
        return f"{settings.FRONTEND_URL.rstrip('/')}/link/{request.token}"

    async def pending(self, token: str) -> ChannelLinkRequest | None:
        """The request behind a URL, for the page to say which account it is.

        A confirmation page that shows only "connect your account" asks somebody
        to trust a URL. Naming the chat account is what makes the answer theirs
        to give.
        """
        return await channel_link_request_repo.get_valid(
            self.db, token=token, now=datetime.now(UTC)
        )

    async def confirm(self, token: str, user_id: UUID) -> ChannelLinkRequest | None:
        """Attach the chat account behind `token` to `user_id`.

        Returns the request that was spent, or None if the token is unknown or
        expired - the two answer the same way, because the difference is not
        something the person clicking can act on differently.
        """
        request = await self.pending(token)
        if request is None:
            return None

        # get_or_create, not get-then-create: a concurrent inbound message could
        # otherwise collide on the identity's unique key and 500 the confirm (#1113).
        # The upsert leaves an existing user_id alone, so the link is the update below.
        identity = await channel_identity_repo.get_or_create(
            self.db,
            platform=request.platform,
            platform_user_id=request.platform_user_id,
            platform_username=request.platform_username,
            platform_display_name=request.platform_display_name,
            user_id=user_id,
        )
        if identity.user_id != user_id:
            await channel_identity_repo.update(
                self.db, db_identity=identity, update_data={"user_id": user_id}
            )

        await channel_link_request_repo.delete_by_id(self.db, request.id)
        return request

    async def linked(self, user_id: UUID) -> list[ChannelIdentity]:
        """The chat accounts this person has connected."""
        return await channel_identity_repo.list_for_user(self.db, user_id=user_id)

    async def places(
        self, user_id: UUID, identities: list[ChannelIdentity]
    ) -> dict[UUID, list[LinkedPlace]]:
        """Where each of these accounts has been used, keyed by identity.

        "Mattermost" is all a `ChannelIdentity` can say about itself - it is
        keyed on the platform and the account, never on a bot - and on a
        deployment with two Mattermost servers that does not say which company's
        chat somebody just connected. The sessions hanging off the identity are
        the only record of where it has actually been used, so this reads them
        and names the bot, the host and what answers there.

        Narrowed twice, and both matter. A bot in an organization this person is
        not a member of is skipped outright - a chat account is not scoped to a
        tenant, so an account used in two companies must not tell either about
        the other. And within an organization the agents are filtered through
        `resolve_access`, because an agent somebody may not read is one they
        should not learn the name of from their own profile page.

        Takes the identities rather than re-reading them: the caller has just
        listed them to render the rows, and two queries for one answer is how
        a page comes to show a row the panel beside it does not have.
        """
        by_identity = await channel_session_repo.bots_by_identity(
            self.db, identity_ids=[identity.id for identity in identities]
        )
        contexts: dict[UUID, AuthContext | None] = {}
        places: dict[UUID, list[LinkedPlace]] = {}
        for identity_id, bots in by_identity.items():
            for bot in bots:
                if bot.organization_id not in contexts:
                    contexts[bot.organization_id] = await self._as_member(
                        user_id, bot.organization_id
                    )
                ctx = contexts[bot.organization_id]
                if ctx is None:
                    continue
                places.setdefault(identity_id, []).append(
                    LinkedPlace(
                        bot_id=bot.id,
                        bot_name=bot.name,
                        host=_host_of(bot.api_base_url),
                        agents=await self._visible_agents(ctx, bot.id),
                    )
                )
        return places

    async def _as_member(self, user_id: UUID, organization_id: UUID) -> AuthContext | None:
        """This person's context inside one organization, or `None` if they are
        not in it.

        Built here rather than taken from the request because this endpoint is
        under `/me`: it answers about a person, and a person's chat account
        reaches whichever organizations they belong to - not the one whose
        header happened to be on the request.
        """
        membership = await member_repo.get(
            self.db, organization_id=organization_id, user_id=user_id
        )
        if membership is None:
            return None
        return AuthContext(user_id=user_id, organization_id=organization_id, role=membership.role)

    async def _visible_agents(self, ctx: AuthContext, bot_id: UUID) -> list[LinkedAgent]:
        """What answers on this bot, as far as this reader is concerned."""
        exposed = await agent_exposure_repo.list_active_for_bot(self.db, channel_bot_id=bot_id)
        visible: list[LinkedAgent] = []
        for _, agent in exposed:
            if await resolve_access(self.db, ctx, agent, Perm.AGENTS_VIEW, resource_type=AGENT):
                visible.append(
                    LinkedAgent(
                        id=agent.id,
                        name=agent.name,
                        slug=agent.slug,
                        has_avatar=agent.has_avatar,
                    )
                )
        return visible

    async def unlink(self, user_id: UUID, identity_id: UUID) -> bool:
        """Disconnect one chat account, if it is this person's.

        Returns whether anything was disconnected. The row survives with
        `user_id` cleared rather than being deleted: it carries the chat
        account's own id, and deleting it would lose the sessions and
        conversations that hang off it while the person keeps talking to the bot
        from the same account.

        Scoped by owner rather than by id alone - an identity belongs to whoever
        claimed it, and an endpoint that unlinks by id is one that unlinks
        somebody else's.
        """
        for identity in await self.linked(user_id):
            if identity.id == identity_id:
                await channel_identity_repo.update(
                    self.db, db_identity=identity, update_data={"user_id": None}
                )
                return True
        return False
