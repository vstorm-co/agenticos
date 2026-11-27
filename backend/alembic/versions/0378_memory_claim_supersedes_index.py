"""Index correction links so erasure can find references to deleted claims."""

import sqlalchemy as sa

from alembic import op

revision: str = "0378_memory_claim_supersedes_idx"
down_revision: str = "0377_memory_policy"
branch_labels: None = None
depends_on: None = None


_NAME = "ix_memory_claims_supersedes"
_TABLE = "memory_claims"


def upgrade() -> None:
    context = op.get_context()
    if context.as_sql:
        op.create_index(
            _NAME, _TABLE, ["supersedes_id"], postgresql_where=sa.text("supersedes_id IS NOT NULL")
        )
        return
    with context.autocommit_block():
        # A cancelled concurrent build can leave an invalid index with this name.
        op.drop_index(_NAME, table_name=_TABLE, if_exists=True, postgresql_concurrently=True)
        op.create_index(
            _NAME,
            _TABLE,
            ["supersedes_id"],
            postgresql_where=sa.text("supersedes_id IS NOT NULL"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    context = op.get_context()
    if context.as_sql:
        op.drop_index(_NAME, table_name=_TABLE)
        return
    with context.autocommit_block():
        op.drop_index(_NAME, table_name=_TABLE, if_exists=True, postgresql_concurrently=True)
