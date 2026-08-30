"""A member nominates which of their MCP accounts an agent speaks as (#1342).

A binding flagged `use_personal_when_available` substitutes the runner's own
connection for the organization's, in a conversation that holds only them. That
worked for one account and declined to guess at two: nothing recorded which
Notion workspace somebody meant, and picking the older silently is worse than
answering as the organization.

So the choice is recorded where it belongs - on the connection the member owns.
The partial unique index is the whole of the constraint: one default per person
per catalog entry, and only for a personal row, because an organization's
connection is bound by id and has nothing to nominate.

Nothing is backfilled. A member with exactly one account still needs no default
- the substitution takes the single account whether or not it is marked - so an
upgrade changes nobody's behaviour, and a member with two is asked the first
time it matters rather than having one chosen for them by a migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0063_mcp_connection_is_default"
down_revision: str | None = "0062_org_chat_approval_waiver"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "uq_mcp_connections_user_default",
        "mcp_connections",
        ["user_id", "catalog_key"],
        unique=True,
        postgresql_where=sa.text("scope = 'user' AND is_default AND catalog_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_mcp_connections_user_default", table_name="mcp_connections")
    op.drop_column("mcp_connections", "is_default")
