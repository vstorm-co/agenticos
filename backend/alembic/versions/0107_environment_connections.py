"""Let an environment answer a binding with a test system, and keep what evals withheld.

`agent_environment_connections` is the per-environment override: where the
spec binds an MCP connection or a vault secret, an environment can name a test
one instead - a sandbox CRM, a test mailbox - so staging runs the same version
as production without touching production systems. The spec is unchanged; the
override is operational state, like the environment's Logfire project. The test
side is `SET NULL` on delete and a null test side means the binding is off in
that environment, never that it falls back to production.

`intercepted_tool_calls` holds the calls an isolated run (an eval) answered
without executing: a writing tool with no test connection, or a call answered
from - or missing from - the original run's recording, and a call an approval
gate would have held, which an isolated run cannot ask about. Trajectory scoring reads
the arguments the agent meant to send from here.

Both tables are new, so nothing is backfilled.

Revision ID: 0107_environment_connections
Revises: 0105_workspace_directories
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0107_environment_connections"
down_revision: str | None = "0105_workspace_directories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_environment_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("environment_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("production_id", sa.UUID(), nullable=False),
        sa.Column("test_connection_id", sa.UUID(), nullable=True),
        sa.Column("test_secret_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('mcp', 'secret')", name="ck_environment_connection_kind"),
        sa.CheckConstraint(
            "(kind = 'mcp' AND test_secret_id IS NULL) "
            "OR (kind = 'secret' AND test_connection_id IS NULL)",
            name="ck_environment_connection_test_side",
        ),
        sa.ForeignKeyConstraint(["environment_id"], ["agent_environments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["test_connection_id"], ["mcp_connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["test_secret_id"], ["organization_secrets.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "environment_id", "kind", "production_id", name="uq_environment_connection_target"
        ),
    )
    op.create_index(
        "agent_environment_connections_environment_id_idx",
        "agent_environment_connections",
        ["environment_id"],
        unique=False,
    )
    op.create_index(
        "agent_environment_connections_organization_id_idx",
        "agent_environment_connections",
        ["organization_id"],
        unique=False,
    )

    op.create_table(
        "intercepted_tool_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_id", sa.String(length=256), nullable=False),
        sa.Column(
            "args",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('blocked', 'replayed', 'divergent')",
            name="ck_intercepted_tool_call_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'blocked' AND reason IS NOT NULL AND reason IN ('writes', 'needs_approval')) "
            "OR (outcome <> 'blocked' AND reason IS NULL)",
            name="ck_intercepted_tool_call_reason",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "intercepted_tool_calls_organization_id_idx",
        "intercepted_tool_calls",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_intercepted_tool_calls_run_sequence",
        "intercepted_tool_calls",
        ["run_id", "sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_intercepted_tool_calls_run_sequence", table_name="intercepted_tool_calls")
    op.drop_index("intercepted_tool_calls_organization_id_idx", table_name="intercepted_tool_calls")
    op.drop_table("intercepted_tool_calls")
    op.drop_index(
        "agent_environment_connections_organization_id_idx",
        table_name="agent_environment_connections",
    )
    op.drop_index(
        "agent_environment_connections_environment_id_idx",
        table_name="agent_environment_connections",
    )
    op.drop_table("agent_environment_connections")
