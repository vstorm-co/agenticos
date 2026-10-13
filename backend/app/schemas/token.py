"""Token schemas."""

from typing import Literal

from app.schemas.base import BaseSchema


class Token(BaseSchema):
    """OAuth2 token response with refresh token."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MagicLinkToken(Token):
    """A token pair, and where the link that produced it was headed.

    Its own schema rather than a nullable field on :class:`Token`: every other
    token response - the password login, the refresh - has no return path to
    carry, and a field that is always null on three of four responses is one a
    client learns to ignore (#1214).
    """

    return_to: str | None = None


class TokenPayload(BaseSchema):
    """JWT token payload."""

    sub: str | None = None
    exp: int | None = None
    type: Literal["access", "refresh"] | None = None


class RefreshTokenRequest(BaseSchema):
    """Request body for token refresh."""

    refresh_token: str


class OAuthExchangeRequest(BaseSchema):
    """Request body swapping a single-use OAuth code for its token pair."""

    code: str
