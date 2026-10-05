"""Keep a stored workspace's empty directories beside its files.

pydantic-ai-backend 0.2.30 moved the agent's files onto Pydantic AI workspaces,
and the `StateBackend` a `state` workspace is stored as became a filesystem with
directories of its own: one `make_dir` created, or one the agent emptied, still
exists. `files` cannot say so - it holds files by path - so the document is
stored as both, the way the library persists it. Existing rows keep null, which
loads as no directories created: every directory holding a file exists anyway,
so their trees are unchanged.

Revision ID: 0104_workspace_directories
Revises: 0103_skill_library_fingerprint
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0104_workspace_directories"
down_revision: str | None = "0103_skill_library_fingerprint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_workspaces",
        sa.Column("directories", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_workspaces", "directories")
