"""Shop agent background jobs (D3 B62).

Revision ID: 0115_shop_agent_background_jobs
Revises: 0114_shop_ai_persona_settings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0115_shop_agent_background_jobs"
down_revision: str | None = "0114_shop_ai_persona_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_agent_background_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("minerp_tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(length=16), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("notify_channels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("digest_interval_hours", sa.Integer(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("shop_agent_background_jobs_conversation_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("shop_agent_background_jobs_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("shop_agent_background_jobs_pkey")),
    )
    op.create_index(
        "ix_shop_agent_background_jobs_mtenant",
        "shop_agent_background_jobs",
        ["minerp_tenant_id"],
    )
    op.create_index(
        "ix_shop_agent_background_jobs_status",
        "shop_agent_background_jobs",
        ["status"],
    )
    op.create_index(
        "ix_shop_agent_background_jobs_next_run_at",
        "shop_agent_background_jobs",
        ["next_run_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_shop_agent_background_jobs_next_run_at", table_name="shop_agent_background_jobs")
    op.drop_index("ix_shop_agent_background_jobs_status", table_name="shop_agent_background_jobs")
    op.drop_index("ix_shop_agent_background_jobs_mtenant", table_name="shop_agent_background_jobs")
    op.drop_table("shop_agent_background_jobs")
