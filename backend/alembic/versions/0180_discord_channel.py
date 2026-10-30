"""A Discord bot can be an agent's exposure surface (#2079).

Revision ID: 0180_discord_channel
Revises: 0179_channel_history_version
Create Date: 2026-10-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0180_discord_channel"
down_revision: str | None = "0179_channel_history_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SURFACE_CHECK = "agent_exposures_ck_exposure_surface_check"


def upgrade() -> None:
    op.drop_constraint(op.f(_SURFACE_CHECK), "agent_exposures", type_="check")
    op.create_check_constraint(
        op.f(_SURFACE_CHECK),
        "agent_exposures",
        "surface IN ('slack', 'telegram', 'mattermost', 'teams', 'discord')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_exposures WHERE surface = 'discord'")
    op.drop_constraint(op.f(_SURFACE_CHECK), "agent_exposures", type_="check")
    op.create_check_constraint(
        op.f(_SURFACE_CHECK),
        "agent_exposures",
        "surface IN ('slack', 'telegram', 'mattermost', 'teams')",
    )
