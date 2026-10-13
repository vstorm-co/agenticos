"""A human name for a connection, beside the slug the model reads (#1341).

`mcp_connections.name` is the tool prefix. It is constrained to
`^[a-z0-9][a-z0-9-]{0,31}$` because that is what a tool name can carry, and it
is unique per owner because two servers answering to one prefix is ambiguous to
the model. All of which makes it a poor label for a person: an organization
holding two Notion accounts ends up choosing between `notion` and `notion-2`,
which says nothing about which workspace either one reaches.

So `label` is what a person reads and `name` stays what the model sees. Free
text, optional, and nothing is backfilled - a connection with no label shows its
slug, which is exactly what it showed before. Not unique: two people may
reasonably describe two accounts the same way, and the constraint that matters
is on the prefix.

Deliberately not a replacement. The slug stays on screen beside the label
wherever both exist, because a run's tool calls are recorded under the prefix -
and a label that hid it would leave "why did it call `notion-2_search`"
unanswerable from the page that names the account.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0065_mcp_connection_label"
down_revision: str | None = "0064_mcp_connection_is_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_connections", sa.Column("label", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_connections", "label")
