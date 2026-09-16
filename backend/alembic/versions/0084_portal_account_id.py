"""The provider's own id for the account a portal grant is on.

A GitHub App has **one** webhook URL and one signing secret for every
installation, so a delivery cannot name a trigger the way the per-trigger URL
does today. What it carries is `installation.id`, and that has to select the
grant before the signature can be checked against that organization's own
webhook secret - which makes it a query rather than a field inside the encrypted
`oauth_payload` (#1072).

Nullable, because every grant that exists today has no such id and needs none;
indexed, because the lookup is on the delivery path; and not unique, because two
organizations could in principle hold grants GitHub numbered the same and the
signature is what settles which one a delivery belongs to.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0084_portal_account_id"
down_revision: str | Sequence[str] | None = "0080_audit_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_connections", sa.Column("portal_account_id", sa.String(64), nullable=True))
    op.create_index(
        "mcp_connections_portal_account_id_idx", "mcp_connections", ["portal_account_id"]
    )


def downgrade() -> None:
    op.drop_index("mcp_connections_portal_account_id_idx", table_name="mcp_connections")
    op.drop_column("mcp_connections", "portal_account_id")
