"""Add organization-scoped Tailscale connections and their isolated worker pool.

Connection state is stored in separately encrypted payload columns. Downgrade
refuses to remove connections or network-pool jobs, rather than discarding
identities or handing queued work to an older worker.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0347_network_connections"
down_revision: str = "0346_merge_t3_v1850"
branch_labels: None = None
depends_on: None = None


_POOL_BEFORE = "'agent', 'eval', 'ingest', 'system', 'workflow'"
_POOL_AFTER = "'agent', 'eval', 'ingest', 'system', 'workflow', 'network'"


def upgrade() -> None:
    op.create_table(
        "network_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column(
            "visibility", sa.String(length=16), server_default=sa.text("'org'"), nullable=False
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "desired_state",
            sa.String(length=16),
            server_default=sa.text("'paused'"),
            nullable=False,
        ),
        sa.Column(
            "auth_state",
            sa.String(length=32),
            server_default=sa.text("'not_connected'"),
            nullable=False,
        ),
        sa.Column(
            "runtime_state",
            sa.String(length=16),
            server_default=sa.text("'stopped'"),
            nullable=False,
        ),
        sa.Column(
            "cleanup_state", sa.String(length=16), server_default=sa.text("'none'"), nullable=False
        ),
        sa.Column("policy_generation", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("state_payload", sa.Text(), nullable=True),
        sa.Column("login_payload", sa.Text(), nullable=True),
        sa.Column("secret_key_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("enrollment_id", sa.UUID(), nullable=True),
        sa.Column("enrollment_user_id", sa.UUID(), nullable=True),
        sa.Column("enrollment_session_id", sa.UUID(), nullable=True),
        sa.Column("enrollment_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tailnet_name", sa.String(length=255), nullable=True),
        sa.Column("node_id", sa.String(length=128), nullable=True),
        sa.Column(
            "peers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("lease_id", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_sequence", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("network_connections_pkey")),
        sa.UniqueConstraint("id", "organization_id", name="uq_network_connection_id_org"),
        sa.UniqueConstraint("enrollment_id", name="uq_network_connection_enrollment_id"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("network_connections_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("network_connections_owner_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["enrollment_user_id"],
            ["users.id"],
            name=op.f("network_connections_enrollment_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["enrollment_session_id"],
            ["sessions.id"],
            name=op.f("network_connections_enrollment_session_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "scope IN ('user', 'org')",
            name=op.f("network_connections_ck_network_connection_scope_check"),
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'team', 'org')",
            name=op.f("network_connections_ck_network_connection_visibility_check"),
        ),
        sa.CheckConstraint(
            "scope <> 'user' OR visibility = 'private'",
            name=op.f("network_connections_ck_network_connection_personal_visibility_check"),
        ),
        sa.CheckConstraint(
            "scope = 'org' OR owner_user_id IS NOT NULL OR "
            "(desired_state = 'revoked' AND state_payload IS NULL AND login_payload IS NULL)",
            name=op.f("network_connections_ck_network_connection_personal_owner_or_scrubbed_check"),
        ),
        sa.CheckConstraint(
            "desired_state IN ('active', 'paused', 'revoked')",
            name=op.f("network_connections_ck_network_connection_desired_state_check"),
        ),
        sa.CheckConstraint(
            "auth_state IN ('not_connected', 'sign_in_required', 'approval_required', "
            "'authenticated', 'expired', 'error')",
            name=op.f("network_connections_ck_network_connection_auth_state_check"),
        ),
        sa.CheckConstraint(
            "runtime_state IN ('stopped', 'starting', 'running', 'unavailable')",
            name=op.f("network_connections_ck_network_connection_runtime_state_check"),
        ),
        sa.CheckConstraint(
            "cleanup_state IN ('none', 'pending', 'manual', 'complete')",
            name=op.f("network_connections_ck_network_connection_cleanup_state_check"),
        ),
        sa.CheckConstraint(
            "policy_generation >= 1",
            name=op.f("network_connections_ck_network_connection_policy_generation_check"),
        ),
        sa.CheckConstraint(
            "state_sequence >= 0",
            name=op.f("network_connections_ck_network_connection_state_sequence_check"),
        ),
        sa.CheckConstraint(
            "secret_key_version >= 1",
            name=op.f("network_connections_ck_network_connection_secret_key_version_check"),
        ),
        sa.CheckConstraint(
            "(lease_id IS NULL) = (lease_expires_at IS NULL)",
            name=op.f("network_connections_ck_network_connection_lease_pair_check"),
        ),
        sa.CheckConstraint(
            "last_error_code IS NULL OR last_error_code IN ("
            "'runtime_unavailable', 'runtime_disconnected', 'invalid_runtime_response', "
            "'invalid_runtime_sequence', 'runtime_failed', 'runtime_timeout', "
            "'control_plane_unavailable', 'runtime_frame_too_large', 'authority_revoked', "
            "'enrollment_expired', 'identity_changed', 'lease_lost')",
            name=op.f("network_connections_ck_network_connection_last_error_code_check"),
        ),
    )
    op.create_index(
        op.f("network_connections_organization_id_idx"),
        "network_connections",
        ["organization_id"],
    )
    op.create_index(
        op.f("network_connections_owner_user_id_idx"),
        "network_connections",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_network_connection_org_scope_created",
        "network_connections",
        ["organization_id", "scope", "created_at"],
    )
    op.create_index(
        "ix_network_connection_enrollment_expiry",
        "network_connections",
        ["enrollment_expires_at"],
        postgresql_where=sa.text("enrollment_expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_network_connection_lease_expiry",
        "network_connections",
        ["lease_expires_at"],
        postgresql_where=sa.text("lease_expires_at IS NOT NULL"),
    )

    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(op.f("background_jobs_pool_check"), "background_jobs", type_="check")
    op.execute(
        "ALTER TABLE background_jobs ADD CONSTRAINT background_jobs_pool_check "
        f"CHECK (pool IN ({_POOL_AFTER})) NOT VALID"
    )
    op.execute("ALTER TABLE background_jobs VALIDATE CONSTRAINT background_jobs_pool_check")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE network_connections, background_jobs IN ACCESS EXCLUSIVE MODE")
    used = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM network_connections) OR "
            "EXISTS (SELECT 1 FROM background_jobs WHERE pool = 'network')"
        )
    )
    if used:
        raise RuntimeError("Cannot discard Tailscale connections or network-pool jobs")

    op.drop_constraint(op.f("background_jobs_pool_check"), "background_jobs", type_="check")
    op.create_check_constraint(
        op.f("background_jobs_pool_check"), "background_jobs", f"pool IN ({_POOL_BEFORE})"
    )
    op.drop_table("network_connections")
