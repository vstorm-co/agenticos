"""Let organizations hide the default AgenticOS footer on shared viewers."""

import sqlalchemy as sa

from alembic import op

revision: str = "0306_shared_page_attribution"
down_revision: str = "0305_defer_delete_crosslinks"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "public_agenticos_attribution", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "public_agenticos_attribution")
