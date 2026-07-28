"""Agent runs and tool approvals

Revision ID: 0033_runs
Revises: 0032_agents
Create Date: 2026-07-26

A run is the unit a user waits on, a budget is charged to, a trace attaches to
and an approval belongs to. Costs live on the run rather than in a per-request
ledger: the run is the grain anyone points at, and the request-level detail
already exists in the Logfire trace we link to.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0033_runs"
down_revision = "0032_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL: a deleted version must not take the record of the run with it.
        sa.Column(
            "agent_version_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("surface", sa.String(16), nullable=False, server_default="web"),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("model_label", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        # Numeric, not float: these are summed into monthly totals.
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("cost_is_partial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("logfire_trace_id", sa.String(64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_runs_organization_id", "agent_runs", ["organization_id"])
    op.create_index("ix_agent_runs_agent_id", "agent_runs", ["agent_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    # The monthly-budget query: sum cost for one org over a time window.
    op.create_index("ix_agent_runs_org_started", "agent_runs", ["organization_id", "started_at"])

    op.create_table(
        "tool_approvals",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_id", sa.String(64), nullable=False),
        sa.Column("tool_args", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "decided_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_tool_approval_status",
        ),
    )
    op.create_index("ix_tool_approvals_organization_id", "tool_approvals", ["organization_id"])
    op.create_index("ix_tool_approvals_run_id", "tool_approvals", ["run_id"])
    # The approval queue: pending items for one organization.
    op.create_index("ix_tool_approvals_org_status", "tool_approvals", ["organization_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_tool_approvals_org_status", table_name="tool_approvals")
    op.drop_index("ix_tool_approvals_run_id", table_name="tool_approvals")
    op.drop_index("ix_tool_approvals_organization_id", table_name="tool_approvals")
    op.drop_table("tool_approvals")
    op.drop_index("ix_agent_runs_org_started", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_organization_id", table_name="agent_runs")
    op.drop_table("agent_runs")
