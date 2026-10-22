"""Web Push: browser subscriptions, the deployment's signing key, a `push` channel (#2097).

`push_subscriptions` holds what a browser hands the console when the person
turns on notifications in it. The VAPID signing key every message is signed
with lives on the deployment's settings row, sealed in the vault, and is made
the first time it is needed - so the three columns start null. Both CHECK
constraints on the notification channel widen to `push`: a delivery row per
notification sent to the person's browsers, and a preference per event type.

Revision ID: 0161_web_push
Revises: 0160_session_app
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0161_web_push"
down_revision: str | None = "0160_session_app"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DELIVERIES = ("notification_deliveries", "ck_notification_deliveries_channel")
_PREFERENCES = ("notification_preferences", "ck_notification_preferences_channel")


def _check(constraint: tuple[str, str], condition: str) -> None:
    table, name = constraint
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, condition)


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=128), nullable=False),
        sa.Column("auth", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("push_subscriptions_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("push_subscriptions_pkey")),
        sa.UniqueConstraint("endpoint", name=op.f("push_subscriptions_endpoint_key")),
    )
    op.create_index(
        op.f("push_subscriptions_user_id_idx"), "push_subscriptions", ["user_id"], unique=False
    )
    op.add_column("deployment_settings", sa.Column("vapid_private_key", sa.Text(), nullable=True))
    op.add_column(
        "deployment_settings", sa.Column("vapid_public_key", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "deployment_settings", sa.Column("vapid_key_version", sa.Integer(), nullable=True)
    )
    _check(_DELIVERIES, "channel IN ('email', 'push')")
    _check(_PREFERENCES, "channel IN ('in_app', 'email', 'push')")


def downgrade() -> None:
    op.execute("DELETE FROM notification_deliveries WHERE channel = 'push'")
    op.execute("DELETE FROM notification_preferences WHERE channel = 'push'")
    _check(_DELIVERIES, "channel = 'email'")
    _check(_PREFERENCES, "channel IN ('in_app', 'email')")
    op.drop_column("deployment_settings", "vapid_key_version")
    op.drop_column("deployment_settings", "vapid_public_key")
    op.drop_column("deployment_settings", "vapid_private_key")
    op.drop_index(op.f("push_subscriptions_user_id_idx"), table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
