"""Invite links: one invitation anybody holding the URL can accept

Revision ID: 0051_invite_links
Revises: 0050_run_provider
Create Date: 2026-07-28

Onboarding a team meant sending one invitation per address. This makes the
address optional: a row with `email IS NULL` is a *link*, which an admin pastes
into a channel once. Role, expiry, revocation and the accept path are all
unchanged, which is why it is this table rather than a second one.

`max_uses` bounds it - null is unlimited, and an email invitation ignores it
because an address is its own limit of one. `email_domain` is the guard that
makes an unlimited link defensible: a URL in a channel can be forwarded, and
"anyone at our company" is a very different risk from "anyone with the URL".

The partial unique index on (organization_id, email) for pending rows keeps
working untouched: Postgres treats NULLs as distinct, so an organization can
hold several links while still being unable to have two pending invitations for
one address.
"""

import sqlalchemy as sa

from alembic import op

revision = "0051_invite_links"
down_revision = "0050_run_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("invitations", "email", existing_type=sa.String(length=255), nullable=True)
    op.add_column("invitations", sa.Column("max_uses", sa.Integer(), nullable=True))
    op.add_column(
        "invitations",
        sa.Column("used_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("invitations", sa.Column("email_domain", sa.String(length=255), nullable=True))
    # A link with no address is the only shape that may have no address. Stated
    # as a constraint because the alternative - an email invitation whose
    # address went missing - is one nobody can accept and nothing would notice.
    op.create_check_constraint(
        "ck_invitation_link_or_email",
        "invitations",
        "email IS NOT NULL OR max_uses IS NULL OR max_uses > 0",
    )


def downgrade() -> None:
    # Links cannot survive a column that must hold an address.
    op.execute(sa.text("DELETE FROM invitations WHERE email IS NULL"))
    op.drop_constraint("ck_invitation_link_or_email", "invitations", type_="check")
    op.drop_column("invitations", "email_domain")
    op.drop_column("invitations", "used_count")
    op.drop_column("invitations", "max_uses")
    op.alter_column("invitations", "email", existing_type=sa.String(length=255), nullable=False)
