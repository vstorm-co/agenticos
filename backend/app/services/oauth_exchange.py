"""Single-use exchange codes for the OAuth redirect.

The provider round trip hands the browser a short-lived, single-use code instead
of the token pair itself, so neither an access token nor a refresh token ever
appears in a redirect URL, an access log, or a `Referer` header. The frontend
swaps the code for the pair server-to-server.
"""

from __future__ import annotations

import json
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.clients.redis import RedisClient

_KEY = "oauth:exchange:{code}"
_TTL_SECONDS = 60


class OAuthExchangeService:
    """Mint and redeem the one-time code that stands in for the token pair.

    Example:
        code = await service.issue(access_token=a, refresh_token=r)
        tokens = await service.redeem(code)  # (a, r), then None on any replay
    """

    def __init__(self, redis: RedisClient) -> None:
        self.redis = redis

    async def issue(self, *, access_token: str, refresh_token: str) -> str:
        """Store the token pair under a fresh code and return the code."""
        code = secrets.token_urlsafe(32)
        payload = json.dumps({"access_token": access_token, "refresh_token": refresh_token})
        await self.redis.set(_KEY.format(code=code), payload, ttl=_TTL_SECONDS)
        return code

    async def redeem(self, code: str) -> tuple[str, str] | None:
        """Consume a code and return its token pair, or None if it is unknown.

        The read deletes the key, so a code redeems exactly once; a replay, an
        expired code, and a forged one are indistinguishable and all answer None.
        """
        raw = await self.redis.getdel(_KEY.format(code=code))
        if raw is None:
            return None
        data = json.loads(raw)
        return data["access_token"], data["refresh_token"]
