"""Allow e-mail as a surface an agent can be exposed on (#2082).

Revision ID: 0253_exposure_surface_email
Revises: 0252_exposure_surface_sms
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0253_exposure_surface_email"
down_revision: str | None = "0252_exposure_surface_sms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = "surface IN ('slack', 'telegram', 'mattermost', 'teams', 'sms')"
_AFTER = "surface IN ('slack', 'telegram', 'mattermost', 'teams', 'sms', 'email')"


def upgrade() -> None:
    op.drop_constraint("ck_exposure_surface", "agent_exposures", type_="check")
    op.create_check_constraint("ck_exposure_surface", "agent_exposures", _AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM agent_exposures WHERE surface = 'email'")
    op.drop_constraint("ck_exposure_surface", "agent_exposures", type_="check")
    op.create_check_constraint("ck_exposure_surface", "agent_exposures", _BEFORE)
