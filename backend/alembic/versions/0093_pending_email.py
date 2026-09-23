"""An address asked for, and not yet proved.

`PATCH /users/me` accepted a new email address and started using it at once, and
nothing proved the person asking could read it. Every mail this deployment sends
goes to that column - an invitation, a magic link, a password reset, an approval
request, a budget alert, and every notification queued for the email channel -
so an account whose address had been changed to somewhere its owner cannot read
is an account whose password-reset link goes to somebody else (#1772).

The request stages here instead. The address moves across when the link sent to
it is confirmed, which is also what makes that link single-use: confirming
clears this column, and a replayed token then finds nothing staged.

Nullable with no backfill: nobody has a change in flight at the moment this
runs, which is exactly what `NULL` says.

Revision ID: 0093_pending_email
Revises: 0092_notification_dismissed
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0093_pending_email"
down_revision: str | Sequence[str] | None = "0092_notification_dismissed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pending_email", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "pending_email")
