"""This deployment's own identity, access policy and notices - one row.

What an installation calls itself, the wordmark and favicon it serves, whose
terms it links to, who may register, and whether it is open at all. All of it in
a single row, guarded by a unique constraint on a column constrained to true, so
a second identity is an `IntegrityError` rather than a deployment that serves
whichever row a query ordered first.

**Nothing is seeded and nothing is backfilled.** No row means "every default",
which is exactly the state of a deployment whose administrator has not opened the
page - so the absence is the initial value rather than something to write. Every
identity column is nullable for the same reason: cleared means "give me the
built-in back", not "render a blank header".

Revision ID: 0037_deployment_settings
Revises: 0036_conversation_reminder_state
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0037_deployment_settings"
down_revision: str | None = "0036_conversation_reminder_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deployment_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("singleton", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("app_name", sa.String(length=64), nullable=True),
        sa.Column("tagline", sa.String(length=160), nullable=True),
        sa.Column("description", sa.String(length=320), nullable=True),
        sa.Column("logo_path", sa.String(length=512), nullable=True),
        sa.Column("favicon_path", sa.String(length=512), nullable=True),
        sa.Column("footer_text", sa.String(length=280), nullable=True),
        sa.Column("terms_url", sa.String(length=512), nullable=True),
        sa.Column("privacy_url", sa.String(length=512), nullable=True),
        sa.Column(
            "signup_mode", sa.String(length=16), server_default=sa.text("'open'"), nullable=False
        ),
        sa.Column(
            "allowed_email_domains",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("announcement", sa.String(length=500), nullable=True),
        sa.Column(
            "announcement_level",
            sa.String(length=16),
            server_default=sa.text("'info'"),
            nullable=False,
        ),
        sa.Column(
            "maintenance_mode", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("maintenance_message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("singleton", name="deployment_settings_singleton_true_check"),
        sa.PrimaryKeyConstraint("id", name="deployment_settings_pkey"),
        sa.UniqueConstraint("singleton", name="deployment_settings_singleton_key"),
    )


def downgrade() -> None:
    op.drop_table("deployment_settings")
