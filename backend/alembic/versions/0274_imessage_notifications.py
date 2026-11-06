"""Allow explicit private iMessage notification routes.

No route or preference is enabled by this migration. Drain workers and update
API/workers together before configuring iMessage. Downgrade drops iMessage
delivery metadata and removes its routine selectors, but cannot recall messages.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0274_imessage_notifications"
down_revision: str | None = "0273_notification_safe_retries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNELS = {
    "notification_routes": "'slack', 'telegram', 'mattermost', 'teams', 'discord', 'sms'",
    "notification_deliveries": "'email', 'push', 'slack', 'telegram', 'mattermost', 'teams', 'discord', 'sms'",
    "notification_preferences": "'in_app', 'email', 'push', 'slack', 'telegram', 'mattermost', 'teams', 'discord', 'sms'",
}


def _constraints(*, imessage: bool) -> None:
    for table, channels in _CHANNELS.items():
        constraint = op.f(f"{table}_ck_{table}_channel_check")
        op.drop_constraint(constraint, table, type_="check")
        allowed = f"{channels}, 'imessage'" if imessage else channels
        op.create_check_constraint(constraint, table, f"channel IN ({allowed})")


def upgrade() -> None:
    _constraints(imessage=True)
    op.drop_constraint("ck_exposure_surface", "agent_exposures", type_="check")
    op.create_check_constraint(
        "ck_exposure_surface",
        "agent_exposures",
        "surface IN ('slack', 'telegram', 'mattermost', 'teams', 'discord', 'sms', 'email', 'imessage')",
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM agent_exposures WHERE surface = 'imessage'"))
    op.drop_constraint("ck_exposure_surface", "agent_exposures", type_="check")
    op.create_check_constraint(
        "ck_exposure_surface",
        "agent_exposures",
        "surface IN ('slack', 'telegram', 'mattermost', 'teams', 'discord', 'sms', 'email')",
    )
    for table in ("notification_deliveries", "notification_preferences", "notification_routes"):
        op.execute(sa.text(f"DELETE FROM {table} WHERE channel = 'imessage'"))
    for table in ("agent_triggers", "watches"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET notification_channels = (SELECT coalesce(jsonb_agg(c), '[]'::jsonb) FROM jsonb_array_elements_text(notification_channels) AS c WHERE c <> 'imessage') WHERE notification_channels IS NOT NULL"
            )
        )
    _constraints(imessage=False)
