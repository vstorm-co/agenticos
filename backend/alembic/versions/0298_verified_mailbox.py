"""Bind invitation inbox access to a proved mailbox.

No backfill: an existing password or OAuth-provider label does not prove mailbox
control in this session. Proof must never pass to other pre-existing sessions.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0298_verified_mailbox"
down_revision: str = "0297_onboarding_completion"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("proved_email", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "proved_email")
