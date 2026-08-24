"""Token schemas."""

from typing import Literal

from app.schemas.base import BaseSchema


class Token(BaseSchema):
    """OAuth2 token response with refresh token."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


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
