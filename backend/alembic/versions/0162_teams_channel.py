"""A Microsoft Teams bot: its Azure registration and the conversations it is in (#1985).

Revision ID: 0162_teams_channel
Revises: 0161_capability_requested
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0162_teams_channel"
down_revision: str | None = "0161_capability_requested"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SURFACE_CHECK = "agent_exposures_ck_exposure_surface_check"


def upgrade() -> None:
    op.create_table(
        "teams_conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("bot_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("service_url", sa.String(length=500), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("conversation_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["channel_bots.id"],
            name=op.f("teams_conversations_bot_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("teams_conversations_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("teams_conversations_pkey")),
        sa.UniqueConstraint("bot_id", "key", name="uq_teams_conversation_bot_key"),
    )
    op.create_index(
        op.f("teams_conversations_bot_id_idx"), "teams_conversations", ["bot_id"], unique=False
    )
    op.create_index(
        op.f("teams_conversations_key_idx"), "teams_conversations", ["key"], unique=False
    )
    op.create_index(
        op.f("teams_conversations_organization_id_idx"),
        "teams_conversations",
        ["organization_id"],
        unique=False,
    )
    op.add_column("agent_triggers", sa.Column("teams_conversation_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("agent_triggers_teams_conversation_id_fkey"),
        "agent_triggers",
        "teams_conversations",
        ["teams_conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("channel_bots", sa.Column("teams_app_id", sa.String(length=64), nullable=True))
    op.add_column("channel_bots", sa.Column("teams_tenant_id", sa.String(length=64), nullable=True))
    op.drop_constraint(op.f(_SURFACE_CHECK), "agent_exposures", type_="check")
    op.create_check_constraint(
        op.f(_SURFACE_CHECK),
        "agent_exposures",
        "surface IN ('slack', 'telegram', 'mattermost', 'teams')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_exposures WHERE surface = 'teams'")
    op.drop_constraint(op.f(_SURFACE_CHECK), "agent_exposures", type_="check")
    op.create_check_constraint(
        op.f(_SURFACE_CHECK),
        "agent_exposures",
        "surface IN ('slack', 'telegram', 'mattermost')",
    )
    op.drop_column("channel_bots", "teams_tenant_id")
    op.drop_column("channel_bots", "teams_app_id")
    op.drop_constraint(
        op.f("agent_triggers_teams_conversation_id_fkey"), "agent_triggers", type_="foreignkey"
    )
    op.drop_column("agent_triggers", "teams_conversation_id")
    op.drop_index(op.f("teams_conversations_organization_id_idx"), table_name="teams_conversations")
    op.drop_index(op.f("teams_conversations_key_idx"), table_name="teams_conversations")
    op.drop_index(op.f("teams_conversations_bot_id_idx"), table_name="teams_conversations")
    op.drop_table("teams_conversations")
