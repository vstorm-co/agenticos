"""Separate finishing the guided setup from snoozing its offer for one day.

A nullable membership timestamp records explicit completion without requiring an
agent or optional settings. Existing dismissals remain snoozes: they cannot prove
that the person visited every step. Legacy account completion is still respected
by the service, and existing agents/chat activity continue to suppress first use.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0297_onboarding_completion"
down_revision: str = "0296_member_onboarding"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "organization_members",
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organization_members", "onboarding_completed_at")
