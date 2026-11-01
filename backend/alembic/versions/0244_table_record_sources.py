"""Keep record write origins distinct from the member authorizing them.

Existing records keep their user metadata; new writes snapshot the actual source.
Internal MCP credentials carry only an agent ID for provenance, never authority.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0244_table_record_sources"
down_revision: str | Sequence[str] | None = "0243_merge_channel_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "virtual_table_records", sa.Column("created_source", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "virtual_table_records", sa.Column("updated_source", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "api_keys", sa.Column("source_agent_id", postgresql.UUID(as_uuid=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("api_keys", "source_agent_id")
    op.drop_column("virtual_table_records", "updated_source")
    op.drop_column("virtual_table_records", "created_source")
