"""Where an organization's browses run: a proxy or a hosted browser (#2130).

`browser_settings` holds one row per organization that chose anything but the
default - a proxy the browser reaches sites through, or a hosted browser reached
over CDP - with the credential referenced in the vault, and the time zone and
language the browser says it has.

Revision ID: 0130_browser_settings
Revises: 0129_message_attachment_context
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0130_browser_settings"
down_revision: str | None = "0129_message_attachment_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "browser_settings",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("proxy_url", sa.String(length=512), nullable=True),
        sa.Column("remote_url", sa.String(length=512), nullable=True),
        sa.Column("remote_key_param", sa.String(length=64), nullable=False),
        sa.Column("secret_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("locale", sa.String(length=35), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["secret_id"], ["organization_secrets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("organization_id"),
    )
    op.create_index("browser_settings_secret_id_idx", "browser_settings", ["secret_id"])


def downgrade() -> None:
    op.drop_index("browser_settings_secret_id_idx", table_name="browser_settings")
    op.drop_table("browser_settings")
