"""Grants can expire: `expires_at` on `resource_grants`.

A share with no expiry is permanent, and permanent shares are what an auditor
asks about first - who can still reach a resource because somebody shared it
months ago and nobody revoked it. With the column, a share can be given a
lifetime at creation, and the repository's access reads exclude expired rows,
so the access stops without anyone deleting the row. The row stays, so the
Sharing panel can still show it, and the owner can renew or revoke it.

Existing group grants receive a 90-day grace period from the migration. New
group grants require an expiry, while member grants may remain permanent.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0304_resource_grant_expires_at"
down_revision: str = "0305_question_nudge"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "resource_grants",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE resource_grants SET expires_at = now() + interval '90 days' "
        "WHERE subject_group_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("resource_grants", "expires_at")
