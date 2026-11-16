"""Store a chosen presentation icon on tables and workflows.

Null keeps the product's default mark. Icons belong to resource metadata and do
not change a table schema version or a workflow's published execution graph.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0321_resource_icons"
down_revision: str = "0320_record_batch_receipts"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("virtual_tables", sa.Column("icon", sa.String(32), nullable=True))
    op.add_column("workflows", sa.Column("icon", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("workflows", "icon")
    op.drop_column("virtual_tables", "icon")
