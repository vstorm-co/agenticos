"""Keep a chat's live browser/desktop independently of an agent run.

The row owns an opaque provider reference and a fenced driver lease. Provider
handles and teardown credentials are vault sealed, and nullable parent keys
retain the cleanup journal after its owner or conversation is removed. Ending
all environments and draining their cleanup jobs is required before downgrade;
dropping a live ownership journal would leave its remote resources behind.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0376_conversation_environments"
down_revision: str | None = "0375_merge_service_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_environments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("vault_organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("agent_version_id", sa.Uuid(), nullable=True),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("execution_target", sa.String(16), nullable=False),
        sa.Column("session_lifetime", sa.String(16), nullable=False),
        sa.Column("idle_seconds", sa.Integer(), nullable=False),
        sa.Column("last_maintained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("provisioning_attempt", sa.Integer(), nullable=False),
        sa.Column("resource_key", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resource_ciphertext", sa.Text(), nullable=True),
        sa.Column("resource_key_version", sa.Integer(), nullable=True),
        sa.Column("refusal_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "organization_id IS NULL OR organization_id = vault_organization_id",
            name=op.f("conversation_environments_vault_scope_check"),
        ),
        sa.CheckConstraint(
            "session_lifetime IN ('run', 'conversation')",
            name=op.f("conversation_environments_session_lifetime_check"),
        ),
        sa.CheckConstraint(
            "idle_seconds BETWEEN 60 AND 86400",
            name=op.f("conversation_environments_idle_seconds_check"),
        ),
        sa.CheckConstraint(
            "execution_target IN ('agent', 'project')",
            name=op.f("conversation_environments_execution_target_check"),
        ),
        sa.CheckConstraint(
            "kind IN ('browser', 'desktop')", name=op.f("conversation_environments_kind_check")
        ),
        sa.CheckConstraint(
            "state IN ('starting', 'ready', 'failed', 'expired')",
            name=op.f("conversation_environments_state_check"),
        ),
        sa.CheckConstraint(
            "revision >= 1 AND provisioning_attempt >= 0",
            name=op.f("conversation_environments_revision_check"),
        ),
        sa.CheckConstraint(
            "(resource_ciphertext IS NULL) = (resource_key_version IS NULL)",
            name=op.f("conversation_environments_resource_key_check"),
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_conversation_environment_tenant",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["source_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "conversation_environments_active_owner_idx",
        "conversation_environments",
        ["organization_id", "user_id", "conversation_id", "agent_id", "kind"],
        unique=True,
        postgresql_where=sa.text("state IN ('starting', 'ready')"),
    )
    op.create_index(
        "conversation_environments_expiry_idx", "conversation_environments", ["expires_at", "id"]
    )

    op.create_index(
        "conversation_environments_resource_key_idx", "conversation_environments", ["resource_key"]
    )
    op.create_table(
        "conversation_environment_drivers",
        sa.Column("resource_key", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("control", sa.String(16), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "control IN ('human', 'agent')",
            name=op.f("conversation_environment_drivers_control_check"),
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "conversation_environment_drivers_expiry_idx",
        "conversation_environment_drivers",
        ["lease_until"],
    )


def downgrade() -> None:
    pending = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM conversation_environments "
            "WHERE state = 'starting' OR resource_ciphertext IS NOT NULL"
        )
    )
    if pending:
        raise RuntimeError(
            "End conversation environments and drain their cleanup jobs before downgrade"
        )
    op.drop_index(
        "conversation_environments_resource_key_idx", table_name="conversation_environments"
    )
    op.drop_index("conversation_environments_expiry_idx", table_name="conversation_environments")
    op.drop_index(
        "conversation_environments_active_owner_idx", table_name="conversation_environments"
    )
    op.drop_table("conversation_environments")
    op.drop_index(
        "conversation_environment_drivers_expiry_idx", table_name="conversation_environment_drivers"
    )
    op.drop_table("conversation_environment_drivers")
