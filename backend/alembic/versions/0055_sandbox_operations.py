import sqlalchemy as sa

from alembic import op

"""What an agent did in a sandbox, recorded on our side rather than the service's

Revision ID: 0055_sandbox_operations
Revises: 0054_portal_connections
Create Date: 2026-08-21

The sandbox service's activity log is a 200-entry ring buffer in that process's
memory, and its `after` parameter is a polling cursor rather than a page - so what
the buffer dropped cannot be asked for, a conversation worked in all day has lost
its morning, and restarting `sandboxd` loses every log on the host. Nothing outside
that process ever saw the entries, so there was no audit of what an agent did in a
sandbox that outlived the service's uptime (agenticos#1061).

Every workspace tool call already passes through this application, so the write is
ours to make. These rows carry the same facts the service records plus the two it
cannot know - which agent and which run - and deliberately carry **no** file
contents and no command output: that is what makes the log an audit rather than a
way to read somebody's work.

Two composite indexes rather than one: the read is "this organization's, newest
first", usually narrowed to a session. Both are led by `organization_id`, which is
not optional - one `sandboxd` serves every tenant registered at its address.
"""

revision = "0055_sandbox_operations"
down_revision = "0054_portal_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sandbox_operations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("session_key", sa.String(length=128), nullable=False),
        sa.Column("op", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=512), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "duration_ms >= 0", name=op.f("sandbox_operations_ck_sandbox_operation_duration_check")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("sandbox_operations_agent_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("sandbox_operations_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("sandbox_operations_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("sandbox_operations_pkey")),
    )
    op.create_index(
        "sandbox_operations_org_created_idx",
        "sandbox_operations",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("sandbox_operations_organization_id_idx"),
        "sandbox_operations",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "sandbox_operations_session_created_idx",
        "sandbox_operations",
        ["organization_id", "session_key", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("sandbox_operations_session_created_idx", table_name="sandbox_operations")
    op.drop_index(op.f("sandbox_operations_organization_id_idx"), table_name="sandbox_operations")
    op.drop_index("sandbox_operations_org_created_idx", table_name="sandbox_operations")
    op.drop_table("sandbox_operations")
