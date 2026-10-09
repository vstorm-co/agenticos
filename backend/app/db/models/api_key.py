"""Organization API keys - how a script, a Postman collection or an MCP client
acts on the platform without a browser session (#1794).

A key belongs to an organization and is issued by one of its members. It is the
member's authority handed to a program, narrowed: what it may do is the scopes
it was issued with intersected with what its issuer may do *now*, so it never
outlives or outranks the person behind it.

Only a SHA-256 of the key is stored. A key is a random 256-bit secret that is
only ever compared, never read back, so the vault (which exists for credentials
the platform must use) is the wrong home for it - and a slow password hash buys
nothing against a secret nobody can guess. The visible `prefix` is what a list
shows and what a lookup starts from.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy import false as sql_false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The member whose authority the key carries. Deleting the account deletes
    # its keys: a key with nobody behind it would have no role to narrow.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A credential the platform minted for its own use - the in-app assistant's,
    # for the person a run acts for (#1798). Never listed, and short-lived.
    internal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_false()
    )
    # Set for an access token an OAuth client received (#2059): the grant it came
    # from, so revoking the grant revokes it. Null for a key a person issued.
    oauth_grant_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("oauth_grants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<ApiKey(prefix={self.prefix}, org={self.organization_id})>"
