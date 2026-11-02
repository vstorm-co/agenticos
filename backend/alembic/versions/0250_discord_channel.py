"""A Discord bot can be an agent's exposure surface (#2079).

Revision ID: 0250_discord_channel
Revises: 0249_message_guardrail_refused
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0250_discord_channel"
down_revision: str | None = "0249_message_guardrail_refused"
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
