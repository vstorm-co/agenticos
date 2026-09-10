"""Server-side staging for an invitation deep link.

An unauthenticated invitee who follows `/invitations/<token>` arrives holding a
bearer credential in the URL. Carrying it through the sign-in round trip - in a
`returnTo` query, in browser history, in `sessionStorage` - is how the token
ends up somewhere a script can read it. Instead the browser exchanges it here,
before the redirect to login, for an opaque single-use handle kept in Redis.

The handle rides an `httpOnly` cookie the frontend's server layer sets, so no
script ever reads it, and the raw token never leaves the server after the
exchange. After sign-in the handle is redeemed and the invitation accepted as the
now-authenticated user; a first-time registrant's admission check peeks it without
consuming it, so the one handle still closes the acceptance afterwards.

This is the same shape as :mod:`app.services.oauth_exchange`: a short-lived,
single-use code standing in for a credential so the credential itself never rides
a URL. Redis is the store for the same reason - ephemeral, expiring, and never an
at-rest record - so nothing here goes through the vault.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.clients.redis import RedisClient

_KEY = "invitation:stage:{handle}"

# A sign-in round trip, comfortably: a password login is seconds, but an OAuth
# detour or a first-time registration is minutes, and a handle that expired
# mid-login would strand the invitee. Shorter than the invitation's own lifetime
# either way, and the accept re-checks that - so a stale handle costs a re-click
# of the link, not a lost invitation.
_TTL_SECONDS = 1800


class InvitationStagingService:
    """Mint, peek and redeem the one-time handle that stands in for an invitation token.

    Example:
        handle = await service.stage(token)
        token = await service.peek(handle)    # registration admission, non-consuming
        token = await service.redeem(handle)  # acceptance, then None on any replay
    """

    def __init__(self, redis: RedisClient) -> None:
        self.redis = redis

    async def stage(self, token: str) -> str:
        """Store an invitation token under a fresh handle and return the handle."""
        handle = secrets.token_urlsafe(32)
        await self.redis.set(_KEY.format(handle=handle), token, ttl=_TTL_SECONDS)
        return handle

    async def peek(self, handle: str) -> str | None:
        """The staged token for a handle without consuming it, or None if unknown.

        For the registration admission check, which needs the invitation to admit
        the new account but must leave the handle intact for the acceptance that
        follows sign-in.
        """
        return await self.redis.get(_KEY.format(handle=handle))

    async def redeem(self, handle: str) -> str | None:
        """Consume a handle and return its token, or None if it is unknown.

        The read deletes the key, so a handle redeems exactly once; a replay, an
        expired handle, and a forged one are indistinguishable and all answer None.
        """
        return await self.redis.getdel(_KEY.format(handle=handle))
