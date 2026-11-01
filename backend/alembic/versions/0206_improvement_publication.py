"""Keep the publication made by an improvement session after reopening it.

Revision ID: 0206_improvement_publication
Revises: 0205_improvement_embedding_spend
Legacy sessions remain unknown rather than guessing from the latest version.
The UUID is a historical pin, like the session's baseline version.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0206_improvement_publication"
down_revision: str | None = "0205_improvement_embedding_spend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("improvement_runs", sa.Column("published_version_id", sa.UUID(), nullable=True))
    op.add_column("improvement_runs", sa.Column("published_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("improvement_runs", "published_version")
    op.drop_column("improvement_runs", "published_version_id")
