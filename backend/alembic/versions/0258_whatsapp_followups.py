"""WhatsApp: wider identifier columns and a held chat notice (#2076).

Revision ID: 0258_whatsapp_followups
Revises: 0257_whatsapp_window
Create Date: 2026-11-04

A business-scoped user id is up to 131 characters, and namespaced by organization
(`"{organization}:{id}"`) up to 168. Every column that holds either is widened from
100 to 255. A downgrade narrows them back and fails while a longer value is stored.

A held run may also owe a fixed chat sentence (`held_notice`, its key, never its text),
delivered when the customer writes again.

A customer whose run waits on an approval is nudged once per window before it closes;
`whatsapp_customers.nudged_at` records when.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0258_whatsapp_followups"
down_revision: str | None = "0257_whatsapp_window"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("channel_identities", "platform_user_id"),
    ("channel_link_requests", "platform_user_id"),
    ("channel_sessions", "platform_chat_id"),
    ("whatsapp_customers", "bsuid"),
)


def upgrade() -> None:
    op.add_column(
        "whatsapp_held_runs", sa.Column("held_notice", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "whatsapp_customers",
        sa.Column("nudged_at", sa.DateTime(timezone=True), nullable=True),
    )
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(length=100),
            type_=sa.String(length=255),
            existing_nullable=False,
        )


def downgrade() -> None:
    op.drop_column("whatsapp_customers", "nudged_at")
    op.drop_column("whatsapp_held_runs", "held_notice")
    for table, column in reversed(_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=sa.String(length=255),
            type_=sa.String(length=100),
            existing_nullable=False,
        )
