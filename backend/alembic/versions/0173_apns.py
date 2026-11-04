"""Push to iPhones: device tokens and the organization's APNs key (#2097).

`apns_devices` holds the token the iOS app hands the console once the person
allows notifications. The key every message is signed with is the company's
own - the Apple developer account the app was signed with - so it is an
administrator's to set, on the deployment's settings row, sealed in the vault
like the Web Push key beside it. All six columns start null: no iPhone push
until somebody sets a key.

A separate table rather than a kind of `push_subscriptions`: a Web Push row is
an endpoint and two encryption keys, an APNs row is one token, and making the
keys nullable to share a table would let a browser's row lose them.

Revision ID: 0173_apns
Revises: 0172_web_push
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0173_apns"
down_revision: str | None = "0172_web_push"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "apns_devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(length=200), nullable=False),
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
            name=op.f("apns_devices_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("apns_devices_pkey")),
        sa.UniqueConstraint("token", name=op.f("apns_devices_token_key")),
    )
    op.create_index(op.f("apns_devices_user_id_idx"), "apns_devices", ["user_id"], unique=False)
    op.add_column("deployment_settings", sa.Column("apns_private_key", sa.Text(), nullable=True))
    op.add_column("deployment_settings", sa.Column("apns_key_version", sa.Integer(), nullable=True))
    op.add_column(
        "deployment_settings", sa.Column("apns_key_id", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "deployment_settings", sa.Column("apns_team_id", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "deployment_settings", sa.Column("apns_topic", sa.String(length=155), nullable=True)
    )
    op.add_column("deployment_settings", sa.Column("apns_sandbox", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("deployment_settings", "apns_sandbox")
    op.drop_column("deployment_settings", "apns_topic")
    op.drop_column("deployment_settings", "apns_team_id")
    op.drop_column("deployment_settings", "apns_key_id")
    op.drop_column("deployment_settings", "apns_key_version")
    op.drop_column("deployment_settings", "apns_private_key")
    op.drop_index(op.f("apns_devices_user_id_idx"), table_name="apns_devices")
    op.drop_table("apns_devices")
