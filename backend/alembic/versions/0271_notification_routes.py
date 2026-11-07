"""Explicit private notification routes, never inferred from linked accounts.

Delivery grants are immutable. Replacement clears queued references instead of
redirecting private notifications. Downgrade discards chat preferences/deliveries;
it cannot recall messages already accepted by an external platform. Drain workers
and update API/workers together before using the expanded channel vocabulary.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0271_notification_routes"
down_revision: str | None = "0270_mcp_auth_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_bots",
        sa.Column(
            "authorization_generation",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    op.add_column(
        "channel_identities",
        sa.Column(
            "authorization_generation",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    for table, name, channels in (
        (
            "notification_deliveries",
            "ck_notification_deliveries_channel",
            "'email', 'push', 'slack', 'telegram', 'mattermost', 'teams', 'sms'",
        ),
        (
            "notification_preferences",
            "ck_notification_preferences_channel",
            "'in_app', 'email', 'push', 'slack', 'telegram', 'mattermost', 'teams', 'sms'",
        ),
    ):
        op.drop_constraint(op.f(f"{table}_{name}_check"), table, type_="check")
        op.create_check_constraint(op.f(f"{table}_{name}_check"), table, f"channel IN ({channels})")
    op.create_table(
        "notification_routes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("identity_generation", sa.UUID(), nullable=False),
        sa.Column("bot_generation", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "channel IN ('slack', 'telegram', 'mattermost', 'teams', 'sms')",
            name=op.f("notification_routes_ck_notification_routes_channel_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("notification_routes_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["channel_sessions.id"],
            name=op.f("notification_routes_session_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("notification_routes_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("notification_routes_pkey")),
        sa.UniqueConstraint(
            "organization_id", "user_id", "channel", name="uq_notification_route_owner"
        ),
    )
    op.create_index(
        op.f("notification_routes_user_id_idx"), "notification_routes", ["user_id"], unique=False
    )
    op.create_index(
        op.f("notification_routes_session_id_idx"), "notification_routes", ["session_id"]
    )
    op.add_column("notification_deliveries", sa.Column("route_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("notification_deliveries_route_id_idx"), "notification_deliveries", ["route_id"]
    )
    op.create_foreign_key(
        op.f("notification_deliveries_route_id_fkey"),
        "notification_deliveries",
        "notification_routes",
        ["route_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    for table, name, channels in (
        ("notification_deliveries", "ck_notification_deliveries_channel", "'email', 'push'"),
        (
            "notification_preferences",
            "ck_notification_preferences_channel",
            "'in_app', 'email', 'push'",
        ),
    ):
        op.execute(sa.text(f"DELETE FROM {table} WHERE channel NOT IN ({channels})"))
        op.drop_constraint(op.f(f"{table}_{name}_check"), table, type_="check")
        op.create_check_constraint(op.f(f"{table}_{name}_check"), table, f"channel IN ({channels})")
    for table in ("agent_triggers", "watches"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET notification_channels = (SELECT coalesce(jsonb_agg(c), '[]'::jsonb) FROM jsonb_array_elements_text(notification_channels) AS c WHERE c IN ('email', 'push')) WHERE notification_channels IS NOT NULL"
            )
        )
    op.drop_constraint(
        op.f("notification_deliveries_route_id_fkey"), "notification_deliveries", type_="foreignkey"
    )
    op.drop_index(
        op.f("notification_deliveries_route_id_idx"), table_name="notification_deliveries"
    )
    op.drop_column("notification_deliveries", "route_id")
    op.drop_index(op.f("notification_routes_session_id_idx"), table_name="notification_routes")
    op.drop_index(op.f("notification_routes_user_id_idx"), table_name="notification_routes")
    op.drop_table("notification_routes")
    op.drop_column("channel_identities", "authorization_generation")
    op.drop_column("channel_bots", "authorization_generation")
