"""MCP server connections - a person's own, and an organization's.

Each row is one remote MCP server, and `scope` says who it belongs to.
A `"user"` row is somebody's own (Settings → Your connections) and only
their assistant uses it. An `"org"` row belongs to the organization and
is what an agent spec may bind, because a published agent's reach cannot
depend on whose session happens to run it.

`auth_token` must be recoverable to send as a Bearer header on every
request, so hashing is not an option, but a DB dump alone must not leak
it. Both scopes seal it through :mod:`app.core.vault`; what differs is
who the envelope is bound to - the organization for an `"org"` row, the
owning member for a `"user"` one, which has no organization to bind to
and whose owner may belong to several. `secret_key_version` records
which vault master key sealed this row's secrets; one version governs
every envelope in the row.

`allowed_tools` is NULL when the user exposes every tool the server
offers; otherwise it's the list of unprefixed tool names they picked.

`auth_type` is `"bearer"` (a static token in `auth_token`) or
`"oauth"` (the OAuth 2.1 authorization-code flow, RFC 9728 / 8414 /
7591 + PKCE). For OAuth connections the discovered endpoints, registered
client credentials and access/refresh tokens live vault-sealed in
`oauth_payload` (a JSON blob). An authorization redirect that is still
in flight is staged separately in `oauth_pending_payload` (keyed by the
CSRF token in `oauth_state`) and only replaces `oauth_payload` once
the callback brings back real tokens.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class McpConnection(Base, TimestampMixin):
    """One MCP server connection, owned by a member or by an organization."""

    __tablename__ = "mcp_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_mcp_connections_user_name"),
        # Names identify a server to whoever is configuring an agent and become
        # its tool prefix, so they have to be unambiguous inside an
        # organization. Partial, because a member's own "github" is a different
        # namespace and is not a collision with the organization's.
        Index(
            "uq_mcp_connections_org_name",
            "organization_id",
            "name",
            unique=True,
            postgresql_where=text("scope = 'org' AND purpose = 'mcp'"),
        ),
        # One organization holds one grant per portal, and re-consenting replaces
        # it rather than adding a second: two Gmail grants would be two mailboxes
        # polled under one portal with nothing to say which a trigger meant.
        Index(
            "uq_mcp_connections_org_portal",
            "organization_id",
            "portal_key",
            unique=True,
            postgresql_where=text("purpose = 'portal'"),
        ),
        # One default per person per catalog entry, and only for a personal row:
        # an organization's connection is bound by id and has nothing to
        # nominate. What makes a member holding two Notion accounts able to say
        # which an agent speaks as (#1342).
        Index(
            "uq_mcp_connections_user_default",
            "user_id",
            "catalog_key",
            unique=True,
            postgresql_where=text("scope = 'user' AND is_default AND catalog_key IS NOT NULL"),
        ),
        CheckConstraint("scope IN ('user', 'org')", name="ck_mcp_connection_scope"),
        CheckConstraint("purpose IN ('mcp', 'portal')", name="ck_mcp_connection_purpose"),
        # A portal grant names its portal and nothing else does: the column is what
        # the poller and the trigger card look a connection up by.
        CheckConstraint(
            "(purpose = 'portal') = (portal_key IS NOT NULL)",
            name="ck_mcp_connection_portal_key",
        ),
        CheckConstraint(
            "scope <> 'org' OR organization_id IS NOT NULL",
            name="ck_mcp_connection_org_scope_has_org",
        ),
        # The pair below is what keeps the personal routes off an organization
        # row. They authorize on `user_id` alone, so an organization row that
        # carried one would be editable and deletable by whoever created it,
        # with no `connections:manage` anywhere in the request.
        CheckConstraint(
            "scope <> 'user' OR user_id IS NOT NULL",
            name="ck_mcp_connection_user_scope_has_user",
        ),
        CheckConstraint(
            "scope <> 'org' OR user_id IS NULL",
            name="ck_mcp_connection_org_scope_has_no_user",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The owner of a personal connection, and NULL for an organization one -
    # which is not an omission but the ownership itself. Cascading is right for
    # a personal token: it dies with the account it belonged to.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Who added an organization connection. Recorded for the audit trail, never
    # for authorization - an organization connection must outlive the person who
    # set it up, so this nulls where `user_id` cascades.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # A connection belongs either to one member (scope="user") or to the whole
    # organization (scope="org"). Personal connections keep a developer's own
    # tokens out of everyone else's agents; org connections are what an agent
    # spec can bind to, because a published agent cannot depend on whose
    # session happens to be running it.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scope: Mapped[str] = mapped_column(String(8), nullable=False, default="user", index=True)
    # Which catalog entry this came from, when it was not added by raw URL.
    catalog_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # What a person reads. `name` is the tool prefix and is constrained to what a
    # tool name can carry, which makes it a poor label: two Notion accounts are
    # `notion` and `notion-2`, and neither says which workspace it reaches.
    # Optional, not unique, and never a replacement - the slug stays on screen
    # beside it, because a run's tool calls are recorded under the prefix.
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Every tool the server offered the last time anything probed it - the
    # catalogue `allowed_tools` is chosen from. Recorded so the Builder can list
    # them without holding `connections:manage`, which gates the probe because it
    # dials out to a third party. Null until the connection is next checked.
    last_tools: Mapped[list[dict[str, str]] | None] = mapped_column(JSONB, nullable=True)
    # Which of this member's accounts on one service an agent speaks as, where a
    # binding asked to substitute theirs and they hold more than one. False on
    # every row until somebody chooses: a single account is substituted whether
    # or not it is marked, so nothing needs a default until there is a choice.
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # What this row *is*. `mcp` is a remote MCP server an agent gets tools from -
    # every row before triggers existed. `portal` is a third-party grant a trigger
    # portal spends: an OAuth payload, its scopes and, for a polled portal, the
    # position the poller has read to.
    #
    # One table rather than two, deliberately. Everything a portal grant needs is
    # already here and correct - the sealed payload, `granted_scopes`, the
    # refresh-under-lock with its expiry skew, the pending-consent staging, the
    # status columns - and a second table would be a second copy of the part of
    # this product that is hardest to get right. So MCP becomes a *consumer* of
    # this table rather than its owner, which is what the triggers plan called
    # Phase 0. The price is one column and one filter: every MCP-facing read asks
    # for `purpose = 'mcp'`, because a Gmail grant is not a server anybody should
    # be offered to bind an agent to (#1068).
    purpose: Mapped[str] = mapped_column(String(16), nullable=False, default="mcp", index=True)
    # Which portal a `purpose = 'portal'` row holds the grant for. Null on an MCP row.
    portal_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Where a polled portal's reader has got to - Gmail's `historyId`, and whatever
    # the next polled portal needs. JSONB rather than a column per provider: the
    # shape is the adapter's business and nothing else reads inside it.
    poll_cursor: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # When the poller last asked. Read by the claim so one tick's work is spread
    # rather than every connection being polled by whichever worker gets there.
    polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    auth_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which vault master key sealed this row's secrets - the bearer token and
    # both OAuth payloads. One version per row, so a rotation moves them
    # together and a payload can never be readable while the token beside it is
    # not.
    secret_key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # The OAuth scopes actually consented to, when the account was authorized for
    # more than tool-reading. NULL on every existing connection and read only by
    # the trigger-portal webhook path, which registers a hook and so needs a
    # scope the plain tool connection never asked for; the tool path never looks
    # at it, so an ordinary MCP connect is untouched.
    granted_scopes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    auth_type: Mapped[str] = mapped_column(String(16), nullable=False, default="bearer")
    # CSRF token for an in-flight OAuth authorization redirect; NULL once done.
    oauth_state: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # Fernet-encrypted JSON: endpoints, client creds, tokens. Written only by a
    # completed flow, so a connection that has this is usable right now.
    oauth_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Same shape, for a consent redirect that is still in flight (endpoints,
    # client creds, PKCE verifier, no tokens). Kept apart from oauth_payload so
    # re-authorizing never destroys credentials that still work.
    oauth_pending_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Result of the most recent connectivity check ("ok" / "error").
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User | None] = relationship("User", lazy="joined", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<McpConnection(name={self.name} scope={self.scope} "
            f"url={self.url} enabled={self.is_enabled})>"
        )
