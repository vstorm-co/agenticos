"""Tags on a workflow, for finding one in a long list.

`workflows.tags` is a short list of labels a builder gives a workflow - `sales`,
`nightly` - filtered on by the console's list. It starts empty for every existing
workflow. The downgrade drops it.

Revision ID: 0115_workflow_tags
Revises: 0114_workflow_approvals
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0115_workflow_tags"
down_revision: str | Sequence[str] | None = "0114_workflow_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(length=32)),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("workflows", "tags")
