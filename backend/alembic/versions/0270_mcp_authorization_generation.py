"""Distinguish an account authorization from its reusable connection row.

OAuth re-consent and explicit endpoint/token replacements may select a different
provider identity. Token refresh does not. Existing source policies stay readable
but need explicit review; they cannot infer a historical credential generation.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0270_mcp_auth_generation"
down_revision: str | None = "0269_routine_end_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column(
            "authorization_generation",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_connections", "authorization_generation")
