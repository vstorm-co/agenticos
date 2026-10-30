"""Single-use exchange codes for the OAuth redirect.

The provider round trip hands the browser a short-lived, single-use code instead
of the token pair itself, so neither an access token nor a refresh token ever
appears in a redirect URL, an access log, or a `Referer` header. The frontend
swaps the code for the pair server-to-server.
"""

import base64
import hashlib
import re
import secrets
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from app.core.exceptions import AuthenticationError

if TYPE_CHECKING:
    from app.clients.redis import RedisClient

_KEY = "oauth:exchange:{code}"
_TTL_SECONDS = 60


class _ExchangePayload(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    access_token: str
    refresh_token: str
    code_challenge: str | None = None


def native_code_challenge(client: str | None, nonce: str | None) -> str | None:
    """Native returns require S256 proof; the echoed nonce is only its public hash."""
    if client != "desktop":
        return None
    if nonce is None or re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce) is None:
        raise AuthenticationError(message="Restart sign-in from an updated AgenticOS app")
    return nonce


class OAuthExchangeService:
    """Mint and redeem the one-time code that stands in for the token pair.

    Example:
        code = await service.issue(access_token=a, refresh_token=r)
        tokens = await service.redeem(code)  # (a, r), then None on any replay
    """

    def __init__(self, redis: RedisClient) -> None:
        self.redis = redis

    async def issue(
        self, *, access_token: str, refresh_token: str, code_challenge: str | None = None
    ) -> str:
        """Store the token pair under a fresh code and return the code."""
        code = secrets.token_urlsafe(32)
        payload = _ExchangePayload(
            access_token=access_token, refresh_token=refresh_token, code_challenge=code_challenge
        ).model_dump_json(exclude_none=True)
        await self.redis.set(_KEY.format(code=code), payload, ttl=_TTL_SECONDS)
        return code

    async def redeem(
        self, code: str, *, code_verifier: str | None = None
    ) -> tuple[str, str] | None:
        """Consume a code and return its token pair, or None if it is unknown.

        The read deletes the key, so a code redeems exactly once; a replay, an
        expired code, and a forged one are indistinguishable and all answer None.
        """
        key = _KEY.format(code=code)
        raw = await self.redis.get(key)
        if raw is None:
            return None
        data = _ExchangePayload.model_validate_json(raw)
        if data.code_challenge is not None:
            if (
                code_verifier is None
                or re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", code_verifier) is None
            ):
                return None
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
                .rstrip(b"=")
                .decode("ascii")
            )
            if not secrets.compare_digest(challenge, data.code_challenge):
                return None
        # Check proof before consumption: an intercepted callback cannot burn the
        # legitimate app's code. GETDEL still admits only one concurrent winner.
        consumed = await self.redis.getdel(key)
        if consumed is None or not secrets.compare_digest(consumed.encode(), raw.encode()):
            return None
        return data.access_token, data.refresh_token
