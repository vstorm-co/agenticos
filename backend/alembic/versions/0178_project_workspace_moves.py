"""Track the active project workspace generation and its durable transfer job.

Revision ID: 0178_project_workspace_moves
Revises: 0177_embedding_base_url
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0178_project_workspace_moves"
down_revision: str | None = "0177_embedding_base_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects", sa.Column("workspace_generation", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "projects", sa.Column("workspace_move_job_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "projects_workspace_move_job_id_fkey",
        "projects",
        "background_jobs",
        ["workspace_move_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("projects_workspace_move_job_id_idx", "projects", ["workspace_move_job_id"])


def downgrade() -> None:
    op.drop_index("projects_workspace_move_job_id_idx", table_name="projects")
    op.drop_constraint("projects_workspace_move_job_id_fkey", "projects", type_="foreignkey")
    op.drop_column("projects", "workspace_move_job_id")
    op.drop_column("projects", "workspace_generation")
