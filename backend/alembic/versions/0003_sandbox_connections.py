"""Sandbox connections - where an organization's sandboxes run

Revision ID: 0003_sandbox_connections
Revises: 0002_agent_workspaces
Create Date: 2026-08-03

Three changes, all consequences of one: the address and token a container-backed
workspace needs stop being deployment settings and become a row per
organization, with the credential referenced in the vault rather than sitting in
a process environment.

* `sandbox_connections` is the row. A name, a kind, an address, and a
  `secret_id` pointing at the vault entry that authorises opening a session on
  that host.
* `agent_workspaces.connection_id` records which one holds a workspace, so that
  purging a deleted conversation's sandbox does not have to re-derive the host
  from a spec nobody has in hand at that point. `SET NULL`, because forgetting a
  host must not delete the record of what an agent did on it.
* `agent_exposures.session_scope` lets one surface disagree with the spec about
  who shares a workspace. A Slack channel and a web chat are not the same
  sharing question, and the answer belongs where the surface is configured.

No data migration. `SANDBOXD_URL` and `SANDBOXD_TOKEN` were never released, so
there is nothing deployed to carry forward - a deployment registers its host
through the operator screen.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_sandbox_connections"
down_revision = "0002_agent_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sandbox_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("secret_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("default_runtime", sa.String(length=64), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="sandbox_connections_organization_id_fkey",
            ondelete="CASCADE",
        ),
        # SET NULL, not CASCADE: deleting a key from the vault makes a connection
        # unusable - a state an operator can see and fix - rather than deleting
        # the host and every workspace keyed to it along with the reason.
        sa.ForeignKeyConstraint(
            ["secret_id"],
            ["organization_secrets.id"],
            name="sandbox_connections_secret_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="sandbox_connections_pkey"),
        sa.UniqueConstraint("organization_id", "name", name="uq_sandbox_connection_name"),
    )
    op.create_index(
        op.f("ix_sandbox_connections_organization_id"),
        "sandbox_connections",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sandbox_connections_secret_id"),
        "sandbox_connections",
        ["secret_id"],
        unique=False,
    )

    op.add_column(
        "agent_workspaces",
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "agent_workspaces_connection_id_fkey",
        "agent_workspaces",
        "sandbox_connections",
        ["connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_agent_workspaces_connection_id"),
        "agent_workspaces",
        ["connection_id"],
        unique=False,
    )

    op.add_column(
        "agent_exposures",
        sa.Column("session_scope", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_exposures", "session_scope")
    op.drop_index(op.f("ix_agent_workspaces_connection_id"), table_name="agent_workspaces")
    op.drop_constraint(
        "agent_workspaces_connection_id_fkey", "agent_workspaces", type_="foreignkey"
    )
    op.drop_column("agent_workspaces", "connection_id")
    op.drop_index(op.f("ix_sandbox_connections_secret_id"), table_name="sandbox_connections")
    op.drop_index(op.f("ix_sandbox_connections_organization_id"), table_name="sandbox_connections")
    op.drop_table("sandbox_connections")
