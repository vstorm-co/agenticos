"""A WhatsApp customer's 24-hour window, held runs and the late-answer template (#2076).

Revision ID: 0257_whatsapp_window
Revises: 0256_whatsapp_channel
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0257_whatsapp_window"
down_revision: str | None = "0256_whatsapp_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_customers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("bot_id", sa.UUID(), nullable=False),
        sa.Column("bsuid", sa.String(length=100), nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["bot_id"], ["channel_bots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", "bsuid", name="uq_whatsapp_customer_bot_bsuid"),
    )
    op.create_index(
        op.f("whatsapp_customers_organization_id_idx"),
        "whatsapp_customers",
        ["organization_id"],
    )
    op.create_table(
        "whatsapp_held_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("held_answer", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("held_files", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["whatsapp_customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "customer_id",
            "run_id",
            "message_id",
            name="uq_whatsapp_held_run_customer_run_message",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(op.f("whatsapp_held_runs_message_id_idx"), "whatsapp_held_runs", ["message_id"])
    op.create_index(op.f("whatsapp_held_runs_run_id_idx"), "whatsapp_held_runs", ["run_id"])
    op.add_column(
        "channel_bots",
        sa.Column("whatsapp_late_template", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "agent_runs", sa.Column("undelivered_reason", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "undelivered_reason")
    op.drop_column("channel_bots", "whatsapp_late_template")
    op.drop_index(op.f("whatsapp_held_runs_message_id_idx"), table_name="whatsapp_held_runs")
    op.drop_index(op.f("whatsapp_held_runs_run_id_idx"), table_name="whatsapp_held_runs")
    op.drop_table("whatsapp_held_runs")
    op.drop_index(op.f("whatsapp_customers_organization_id_idx"), table_name="whatsapp_customers")
    op.drop_table("whatsapp_customers")
