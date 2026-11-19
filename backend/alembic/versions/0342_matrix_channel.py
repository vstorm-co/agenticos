"""A Matrix bot can be an agent's exposure surface (#2081).

Revision ID: 0342_matrix_channel
Revises: 0341_workflow_run_tested_step
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0342_matrix_channel"
down_revision: str | None = "0341_workflow_run_tested_step"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SURFACE_CHECK = "agent_exposures_ck_exposure_surface_check"
_SURFACES = "'slack', 'telegram', 'mattermost', 'teams', 'discord', 'sms', 'email', 'imessage'"


def upgrade() -> None:
    op.drop_constraint(op.f(_SURFACE_CHECK), "agent_exposures", type_="check")
    op.create_check_constraint(
        op.f(_SURFACE_CHECK),
        "agent_exposures",
        f"surface IN ({_SURFACES}, 'matrix')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_exposures WHERE surface = 'matrix'")
    op.drop_constraint(op.f(_SURFACE_CHECK), "agent_exposures", type_="check")
    op.create_check_constraint(
        op.f(_SURFACE_CHECK),
        "agent_exposures",
        f"surface IN ({_SURFACES})",
    )
