"""A WhatsApp bot: its Cloud API registration and two-way link confirmation (#2076).

Revision ID: 0256_whatsapp_channel
Revises: 0255_run_chat_notice_sent_at
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0256_whatsapp_channel"
down_revision: str | None = "0255_run_chat_notice_sent_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SURFACE_CHECK = "agent_exposures_ck_exposure_surface_check"
_CONFIRMED_USER_FK = "channel_link_requests_confirmed_user_id_fkey"


def upgrade() -> None:
    op.add_column(
        "channel_bots", sa.Column("whatsapp_phone_number_id", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "channel_bots", sa.Column("whatsapp_account_id", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "channel_bots",
        sa.Column("whatsapp_verify_token_encrypted", sa.String(length=1000), nullable=True),
    )
    op.add_column("channel_link_requests", sa.Column("confirmed_user_id", sa.UUID(), nullable=True))
    op.add_column(
        "channel_link_requests", sa.Column("confirm_code", sa.String(length=12), nullable=True)
    )
    op.create_foreign_key(
        op.f(_CONFIRMED_USER_FK),
        "channel_link_requests",
        "users",
        ["confirmed_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(op.f(_SURFACE_CHECK), "agent_exposures", type_="check")
    op.create_check_constraint(
        op.f(_SURFACE_CHECK),
        "agent_exposures",
        "surface IN ('slack', 'telegram', 'mattermost', 'teams', 'discord', 'whatsapp')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_exposures WHERE surface = 'whatsapp'")
    op.drop_constraint(op.f(_SURFACE_CHECK), "agent_exposures", type_="check")
    op.create_check_constraint(
        op.f(_SURFACE_CHECK),
        "agent_exposures",
        "surface IN ('slack', 'telegram', 'mattermost', 'teams', 'discord')",
    )
    op.drop_constraint(op.f(_CONFIRMED_USER_FK), "channel_link_requests", type_="foreignkey")
    op.drop_column("channel_link_requests", "confirm_code")
    op.drop_column("channel_link_requests", "confirmed_user_id")
    op.drop_column("channel_bots", "whatsapp_verify_token_encrypted")
    op.drop_column("channel_bots", "whatsapp_account_id")
    op.drop_column("channel_bots", "whatsapp_phone_number_id")
