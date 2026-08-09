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
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_link_request import ChannelLinkRequest
from app.repositories import channel_identity_repo, channel_link_request_repo
from app.services.channels.base import IncomingMessage

REQUEST_TTL = timedelta(minutes=15)
"""How long a link URL lives.

It is a bearer credential: whoever opens it claims that chat account. Fifteen
minutes is long enough to switch to a browser and sign in if you were signed out,
and short enough that a URL left in a chat history is not a way in.
"""


class ChannelLinkService:
    """Mint a claim on a chat account, and let a signed-in person confirm it."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def request(self, incoming: IncomingMessage) -> str:
        """Mint a request for this sender and return the URL to send them.

        Any request this chat account already has is dropped first, so a URL that
        scrolled out of view stops working rather than lingering.
        """
        await channel_link_request_repo.delete_for_identity(
            self.db,
            platform=incoming.platform,
            platform_user_id=incoming.platform_user_id,
        )
        request = await channel_link_request_repo.create(
            self.db,
            token=secrets.token_urlsafe(32),
            platform=incoming.platform,
            platform_user_id=incoming.platform_user_id,
            platform_username=incoming.platform_username,
            platform_display_name=incoming.platform_display_name,
            expires_at=datetime.now(UTC) + REQUEST_TTL,
        )
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

        identity = await channel_identity_repo.get_by_platform_user(
            self.db,
            platform=request.platform,
            platform_user_id=request.platform_user_id,
        )
        if identity is None:
            await channel_identity_repo.create(
                self.db,
                platform=request.platform,
                platform_user_id=request.platform_user_id,
                platform_username=request.platform_username,
                platform_display_name=request.platform_display_name,
                user_id=user_id,
            )
        else:
            await channel_identity_repo.update(
                self.db, db_identity=identity, update_data={"user_id": user_id}
            )

        await channel_link_request_repo.delete_by_id(self.db, request.id)
        return request

    async def linked(self, user_id: UUID) -> list[ChannelIdentity]:
        """The chat accounts this person has connected."""
        return await channel_identity_repo.list_for_user(self.db, user_id=user_id)

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
