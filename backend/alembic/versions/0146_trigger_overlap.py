"""What a schedule does while its previous fire is still running (#2219).

`skip`, `queue` or `allow`, per trigger. Existing rows take `skip`: before this
a busy schedule waited and fired once the run ended (`queue`), and that catch-up
fire is what made a slow agent run back to back with no pause between.

Revision ID: 0146_trigger_overlap
Revises: 0145_background_jobs
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0146_trigger_overlap"
down_revision: str | None = "0145_background_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("overlap", sa.String(length=8), server_default="skip", nullable=False),
    )
    op.create_check_constraint(
        "ck_trigger_overlap", "agent_triggers", "overlap IN ('skip', 'queue', 'allow')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_trigger_overlap", "agent_triggers", type_="check")
    op.drop_column("agent_triggers", "overlap")
