"""An organization switch for live data on public pages (#1975).

`organizations.public_live_data` is off for every organization: a page's data reaches
anonymous visitors of its public link or its embeds only where an Owner or Admin has
allowed it. It is a kill switch, not a reset - switching it off hides the data at the
next load and leaves every page's own consent where it was.

Revision ID: 0211_org_public_live_data
Revises: 0210_grant_edit_data
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0211_org_public_live_data"
down_revision: str | Sequence[str] | None = "0210_grant_edit_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("public_live_data", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "public_live_data")
