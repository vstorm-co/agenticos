"""OAuth 2.1 for the platform's MCP server: clients, consents, codes, refresh tokens (#2059).

An MCP client registers itself, sends a person to the console to consent, and
receives an access token it presents to `/mcp`. The access token is an ordinary
organization API key - an `api_keys` row tied to the grant - so everything a key
is held to (narrowing to the consenting member's current role, the public-route
check, the rate limit, the audit trail, revocation) applies without a second
path. What lives here is only what OAuth adds around it.

Only hashes of codes and refresh tokens are stored, as for keys.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OAuthClient(Base, TimestampMixin):
    """A client that registered itself (RFC 7591). Public clients only - no secret."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # The registration response as the client was told it, so a later `/token`
    # call is checked against the redirect URIs it registered.
    info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    def __repr__(self) -> str:
        return f"<OAuthClient(client_id={self.client_id})>"


class OAuthAuthorizationRequest(Base, TimestampMixin):
    """An `/authorize` call waiting for a person to consent in the console."""

    __tablename__ = "oauth_authorization_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<OAuthAuthorizationRequest(id={self.id}, client={self.client_id})>"


class OAuthGrant(Base, TimestampMixin):
    """One consent: a member let a client act as them in one organization."""

    __tablename__ = "oauth_grants"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<OAuthGrant(id={self.id}, client={self.client_id})>"


class OAuthAuthorizationCode(Base, TimestampMixin):
    """A single-use code from a consent. Presented twice, it revokes its grant."""

    __tablename__ = "oauth_authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("oauth_grants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<OAuthAuthorizationCode(grant={self.grant_id})>"


class OAuthRefreshToken(Base, TimestampMixin):
    """A refresh token. Rotated on use; a rotated one presented again revokes its grant."""

    __tablename__ = "oauth_refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("oauth_grants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<OAuthRefreshToken(grant={self.grant_id})>"
