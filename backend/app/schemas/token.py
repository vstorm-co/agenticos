"""Token schemas."""

from typing import Literal
from uuid import UUID

from pydantic import Field

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
    code_verifier: str | None = Field(
        default=None, min_length=43, max_length=128, pattern=r"^[A-Za-z0-9._~-]+$"
    )


class PairingCodeRead(BaseSchema):
    """A single-use code that signs one phone in as the caller (#2097).

    The console draws it as a QR; it expires after `expires_in` seconds.
    """

    code: str
    expires_in: int


class PairingRedeem(BaseSchema):
    """The code a phone scanned, redeemed for a session of its own."""

    code: str


class PairingIdentityRead(BaseSchema):
    """Identity shown before a device explicitly accepts a scanned sign-in."""

    id: UUID
    email: str
    full_name: str | None
