"""Live data bindings on each artifact version.

`artifact_versions.bindings` holds what the page may load: one resolved entry
per binding name. Versions written before this read as none.

Revision ID: 0209_artifact_bindings
Revises: 0208_workflow_step_evals
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0209_artifact_bindings"
down_revision: str | None = "0208_workflow_step_evals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "artifact_versions",
        sa.Column(
            "bindings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("artifact_versions", "bindings")
