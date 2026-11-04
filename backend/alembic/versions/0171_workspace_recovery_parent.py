"""Recovery snapshots share their source workspace's deletion lifetime.

A rejected concurrent merge must preserve the already accepted snapshot without
expanding the shared document past its byte ceiling. The copy commits before the
failing request rolls back. A foreign key, rather than a parsed key or a cleanup
query, ensures erasure also removes a copy inserted while deletion waited for
the source lock. Existing rows remain ordinary workspaces with a null parent.

Revision ID: 0171_workspace_recovery_parent
Revises: 0170_generated_media
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0171_workspace_recovery_parent"
down_revision: str | None = "0170_generated_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_workspaces",
        sa.Column("recovery_of_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "agent_workspaces_recovery_of_id_fkey",
        "agent_workspaces",
        "agent_workspaces",
        ["recovery_of_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("agent_workspaces_recovery_of_id_idx", "agent_workspaces", ["recovery_of_id"])


def downgrade() -> None:
    op.drop_index("agent_workspaces_recovery_of_id_idx", table_name="agent_workspaces")
    op.drop_constraint(
        "agent_workspaces_recovery_of_id_fkey", "agent_workspaces", type_="foreignkey"
    )
    op.drop_column("agent_workspaces", "recovery_of_id")
