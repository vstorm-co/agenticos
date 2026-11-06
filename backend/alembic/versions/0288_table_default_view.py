"""Open a table in a shared saved view chosen by its editors.

Revision ID: 0288_table_default_view
Revises: 0287_task_boards
"""

import sqlalchemy as sa

from alembic import op

revision = "0288_table_default_view"
down_revision = "0287_task_boards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("virtual_tables", sa.Column("default_view_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "virtual_tables_default_view_id_fkey",
        "virtual_tables",
        "table_views",
        ["default_view_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("virtual_tables_default_view_id_idx", "virtual_tables", ["default_view_id"])


def downgrade() -> None:
    op.drop_index("virtual_tables_default_view_id_idx", table_name="virtual_tables")
    op.drop_constraint("virtual_tables_default_view_id_fkey", "virtual_tables", type_="foreignkey")
    op.drop_column("virtual_tables", "default_view_id")
