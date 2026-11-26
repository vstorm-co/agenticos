"""A parked call records whether it is one of the platform's own tools.

A platform call that always asks runs with the platform authority of its run's
person, so only that person may approve it, and only that person reads its
description. Deciding that from the tool's name was wrong: a binding may rename a
capability's tool to anything, the platform's prefix included. The platform
binding marks its own tools on their definitions, and the call now records that
mark when it is parked.

Existing rows are filled from what they hold: a call of no capability whose name
carries the platform's prefix. A capability's call carries its tool's stable id,
so a renamed one is left unmarked.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0375_tool_approval_platform_call"
down_revision: str | None = "0373_project_filesystem_mounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_approvals",
        sa.Column("platform_call", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.execute(
        "UPDATE tool_approvals SET platform_call = true "
        "WHERE capability_tool_id IS NULL AND tool_id LIKE 'agenticos\\_%' ESCAPE '\\'"
    )


def downgrade() -> None:
    op.drop_column("tool_approvals", "platform_call")
