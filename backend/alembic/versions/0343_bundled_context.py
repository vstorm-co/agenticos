"""Identify deployed Context copies and proposals without adopting a same-name file."""

import sqlalchemy as sa

from alembic import op

revision: str = "0343_bundled_context"
down_revision: str = "0342_personal_coding_sessions"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("context_files", sa.Column("library_key", sa.String(64), nullable=True))
    op.add_column("context_files", sa.Column("library_revision", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_context_file_org_library", "context_files", ["organization_id", "library_key"]
    )
    op.add_column("context_proposals", sa.Column("library_revision", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("context_proposals", "library_revision")
    op.drop_constraint("uq_context_file_org_library", "context_files", type_="unique")
    op.drop_column("context_files", "library_revision")
    op.drop_column("context_files", "library_key")
