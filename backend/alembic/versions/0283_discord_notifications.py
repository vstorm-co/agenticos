"""Offer Discord private chats through the existing opt-in notification routes.

No destination is selected automatically; old grants and preferences stay intact.
"""

from alembic import op

revision: str = "0283_discord_notifications"
down_revision: str = "0282_merge_proactivity_main"
branch_labels: None = None
depends_on: None = None

_CHANNELS = {
    "notification_routes": "'slack', 'telegram', 'mattermost', 'teams', 'sms', 'imessage'",
    "notification_deliveries": "'email', 'push', 'slack', 'telegram', 'mattermost', 'teams', 'sms', 'imessage'",
    "notification_preferences": "'in_app', 'email', 'push', 'slack', 'telegram', 'mattermost', 'teams', 'sms', 'imessage'",
}


def _constraints(*, discord: bool) -> None:
    for table, channels in _CHANNELS.items():
        name = op.f(f"{table}_ck_{table}_channel_check")
        op.drop_constraint(name, table, type_="check")
        allowed = f"{channels}, 'discord'" if discord else channels
        op.create_check_constraint(name, table, f"channel IN ({allowed})")


def upgrade() -> None:
    _constraints(discord=True)


def downgrade() -> None:
    for table in _CHANNELS:
        op.execute(f"DELETE FROM {table} WHERE channel = 'discord'")
    _constraints(discord=False)
