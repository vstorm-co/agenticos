"""Opt-in channel observation and bounded pending message windows."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0326_channel_observation"
down_revision: str = "0325_channel_prompt_override"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "agent_exposures",
        sa.Column(
            "observation", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.add_column(
        "agent_exposures",
        sa.Column(
            "observation_generation",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.add_column("agent_exposures", sa.Column("observation_user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "agent_exposures_observation_user_id_fkey",
        "agent_exposures",
        "users",
        ["observation_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "channel_observations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exposure_id",
            sa.UUID(),
            sa.ForeignKey("agent_exposures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation", sa.UUID(), nullable=False),
        sa.Column("admission_hash", sa.String(64), nullable=False),
        sa.Column(
            "conversation_id",
            sa.UUID(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("platform_chat_id", sa.String(512), nullable=False),
        sa.Column("messages", postgresql.JSONB(), nullable=False),
        sa.Column("mentioned", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("checked_revision", sa.Integer(), nullable=False),
        sa.Column("started_revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "exposure_id", "platform_chat_id", name="uq_channel_observation_thread"
        ),
    )
    op.create_index("ix_channel_observations_due", "channel_observations", ["next_check_at"])
    op.create_table(
        "channel_observation_receipts",
        sa.Column(
            "exposure_id",
            sa.UUID(),
            sa.ForeignKey("agent_exposures.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("message_key", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_channel_observation_receipts_expiry", "channel_observation_receipts", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_table("channel_observation_receipts")
    op.drop_table("channel_observations")
    op.drop_constraint(
        "agent_exposures_observation_user_id_fkey", "agent_exposures", type_="foreignkey"
    )
    op.drop_column("agent_exposures", "observation_user_id")
    op.drop_column("agent_exposures", "observation_generation")
    op.drop_column("agent_exposures", "observation")
