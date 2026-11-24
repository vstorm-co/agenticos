"""Organization-bound Tailscale device and network connection state.

The encrypted payloads contain the connector's persistent node state and its
short-lived enrollment URL. They are sealed by the vault under the connection's
owner scope; they are never part of a response schema. A personal row always
belongs to one member inside exactly one organization.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

type NetworkPeerPayload = dict[str, str | bool | list[str] | None]


class NetworkConnection(Base, TimestampMixin):
    """One enrolled Tailscale node, isolated to one organization context."""

    __tablename__ = "network_connections"
    __table_args__ = (
        CheckConstraint("scope IN ('user', 'org')", name="ck_network_connection_scope"),
        CheckConstraint(
            "visibility IN ('private', 'team', 'org')",
            name="ck_network_connection_visibility",
        ),
        CheckConstraint(
            "scope <> 'user' OR visibility = 'private'",
            name="ck_network_connection_personal_visibility",
        ),
        CheckConstraint(
            "scope = 'org' OR owner_user_id IS NOT NULL OR "
            "(desired_state = 'revoked' AND state_payload IS NULL AND login_payload IS NULL)",
            name="ck_network_connection_personal_owner_or_scrubbed",
        ),
        CheckConstraint(
            "desired_state IN ('active', 'paused', 'revoked')",
            name="ck_network_connection_desired_state",
        ),
        CheckConstraint(
            "auth_state IN "
            "('not_connected', 'sign_in_required', 'approval_required', 'authenticated', 'expired', 'error')",
            name="ck_network_connection_auth_state",
        ),
        CheckConstraint(
            "runtime_state IN ('stopped', 'starting', 'running', 'unavailable')",
            name="ck_network_connection_runtime_state",
        ),
        CheckConstraint(
            "cleanup_state IN ('none', 'pending', 'manual', 'complete')",
            name="ck_network_connection_cleanup_state",
        ),
        CheckConstraint("policy_generation >= 1", name="ck_network_connection_policy_generation"),
        CheckConstraint("state_sequence >= 0", name="ck_network_connection_state_sequence"),
        CheckConstraint(
            "(lease_id IS NULL) = (lease_expires_at IS NULL)",
            name="ck_network_connection_lease_pair",
        ),
        CheckConstraint("secret_key_version >= 1", name="ck_network_connection_secret_key_version"),
        CheckConstraint(
            "last_error_code IS NULL OR last_error_code IN ("
            "'runtime_unavailable', 'runtime_disconnected', 'invalid_runtime_response', "
            "'invalid_runtime_sequence', 'runtime_failed', 'runtime_timeout', "
            "'control_plane_unavailable', 'runtime_frame_too_large', 'authority_revoked', "
            "'enrollment_expired', 'identity_changed', 'lease_lost')",
            name="ck_network_connection_last_error_code",
        ),
        UniqueConstraint("id", "organization_id", name="uq_network_connection_id_org"),
        UniqueConstraint("enrollment_id", name="uq_network_connection_enrollment_id"),
        Index(
            "ix_network_connection_org_scope_created",
            "organization_id",
            "scope",
            "created_at",
        ),
        Index(
            "ix_network_connection_enrollment_expiry",
            "enrollment_expires_at",
            postgresql_where=text("enrollment_expires_at IS NOT NULL"),
        ),
        Index(
            "ix_network_connection_lease_expiry",
            "lease_expires_at",
            postgresql_where=text("lease_expires_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The personal owner, or the person who created an organization connection.
    # SET NULL preserves organization resources. The CHECK permits a personal
    # owner to disappear only after both encrypted payloads have been scrubbed.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scope: Mapped[str] = mapped_column(String(8), nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="org", server_default=text("'org'")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    desired_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="paused", server_default=text("'paused'")
    )
    auth_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_connected", server_default=text("'not_connected'")
    )
    runtime_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="stopped", server_default=text("'stopped'")
    )
    cleanup_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default=text("'none'")
    )
    policy_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    # Both payloads are vault-sealed. state_payload survives normal pauses and
    # restarts; login_payload exists only while a bound enrollment attempt is active.
    state_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    login_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_key_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    enrollment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    enrollment_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    enrollment_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    enrollment_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tailnet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    peers: Mapped[list[NetworkPeerPayload]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # One live runtime holds this lease. Revocation increments policy_generation
    # to fence renewals but leaves the lease in place until that process stops.
    lease_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    state_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    def __repr__(self) -> str:
        return (
            f"<NetworkConnection(id={self.id}, scope={self.scope}, "
            f"desired_state={self.desired_state}, auth_state={self.auth_state})>"
        )
