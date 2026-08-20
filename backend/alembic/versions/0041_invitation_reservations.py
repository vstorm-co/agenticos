"""A link's remaining capacity counts the people who registered under it.

`used_count` counts acceptances, and acceptance needs a session - so on an
`invite_only` deployment a one-use link admitted an unbounded number of
*registrations*, because each one only looked at `used_count` and nothing had
consumed a use yet. One link posted anywhere, and closing sign-up was closed to
nobody.

Capacity is reserved at registration instead, keyed on the address that
registered, so `used_count + len(reserved_emails)` is what the link has spent.
Accepting moves an address from the list to the count, which conserves it: a
person who registers through a one-use link can still join.

A reservation nobody accepts is a use spent, and that is the intended reading -
`max_uses` is how many people a link admits, and somebody who created an account
with it was admitted. It dies with the invitation, since an expired or revoked row
admits nobody.

Empty rather than null so the arithmetic and the containment test need no
coalesce, on a column every registration on a gated deployment reads.

Revision ID: 0041_invitation_reservations
Revises: 0040_environment_release_mode
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0041_invitation_reservations"
down_revision: str | None = "0040_environment_release_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invitations",
        sa.Column(
            "reserved_emails",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("invitations", "reserved_emails")
