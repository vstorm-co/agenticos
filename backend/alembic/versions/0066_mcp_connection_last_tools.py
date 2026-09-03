"""What a server offered the last time anything asked it (#1341).

`allowed_tools` is the allowlist somebody chose. Nothing recorded the *catalogue*
it was chosen from, so the only way to see a server's tools was to probe it -
`POST /mcp-connections/{id}/test`, gated on `connections:manage`.

That gate is right for a call that dials out to a third party, and wrong as the
only way to answer "what can this server do". An agent author holds `agents:edit`
and needs the list to choose from; giving them the probe would hand an
unprivileged caller a button that makes outbound requests on demand.

So the probe records what it found. The Builder reads a column instead of
dialling anything, the list is naturally cached, and `last_checked_at` beside it
already says how old the answer is.

Null for every connection until it is next checked, which is what the sweep and
every connect flow already do.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0066_mcp_connection_last_tools"
down_revision: str | None = "0065_mcp_connection_label"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("last_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_connections", "last_tools")
