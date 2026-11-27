"""Fence idle browser viewport fitting without representing a human takeover.

A layout lease uses the same physical exclusion token as agent and human input,
but public control remains idle. Downgrade refuses live layout work and removes
only expired layout tokens before restoring the earlier constraint.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0384_environment_layout_driver"
down_revision: str = "0383_environment_project_files"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("conversation_environment_drivers_control_check"),
        "conversation_environment_drivers",
        type_="check",
    )
    op.create_check_constraint(
        op.f("conversation_environment_drivers_control_check"),
        "conversation_environment_drivers",
        "control IN ('human', 'agent', 'layout')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM conversation_environment_drivers WHERE control='layout' AND lease_until > now())"
        )
    ):
        raise RuntimeError(
            "Stop browser viewport fitting and wait for active layout leases before downgrading"
        )
    connection.execute(
        sa.text("DELETE FROM conversation_environment_drivers WHERE control='layout'")
    )
    op.drop_constraint(
        op.f("conversation_environment_drivers_control_check"),
        "conversation_environment_drivers",
        type_="check",
    )
    op.create_check_constraint(
        op.f("conversation_environment_drivers_control_check"),
        "conversation_environment_drivers",
        "control IN ('human', 'agent')",
    )
