"""Voice conversations: the organization's switch and limits (#54).

Four columns rather than a JSONB blob, in the style of
`0106_org_speech_settings`: each is a limit the database should hold, and a
CHECK can hold a column where it cannot hold a key inside a document. Off by
default, so an upgrade starts no calls anywhere; a 600-second cap below
OpenAI's 60-minute hard stop; 600 minutes a month, nullable so an organization
can rely on its budgets alone. Existing rows take the server defaults.

Revision ID: 0111_org_voice_settings
Revises: 0110_dictation_compressed_audio
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0111_org_voice_settings"
down_revision: str | None = "0110_dictation_compressed_audio"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "voice_conversations_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("voice_in_chat", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "organizations",
        sa.Column("voice_max_call_seconds", sa.Integer(), nullable=False, server_default="600"),
    )
    op.add_column(
        "organizations",
        sa.Column("voice_monthly_minutes", sa.Integer(), nullable=True, server_default="600"),
    )
    op.create_check_constraint(
        op.f("organizations_ck_organization_voice_max_call_seconds_check"),
        "organizations",
        "voice_max_call_seconds BETWEEN 60 AND 3000",
    )
    op.create_check_constraint(
        op.f("organizations_ck_organization_voice_monthly_minutes_check"),
        "organizations",
        "voice_monthly_minutes IS NULL OR voice_monthly_minutes > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("organizations_ck_organization_voice_monthly_minutes_check"),
        "organizations",
        type_="check",
    )
    op.drop_constraint(
        op.f("organizations_ck_organization_voice_max_call_seconds_check"),
        "organizations",
        type_="check",
    )
    for column in (
        "voice_monthly_minutes",
        "voice_max_call_seconds",
        "voice_in_chat",
        "voice_conversations_enabled",
    ):
        op.drop_column("organizations", column)
