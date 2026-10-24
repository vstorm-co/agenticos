"""An agent a workflow step configures in place, owned by its workflow.

Revision ID: 0193_workflow_agents
Revises: 0192_node_run_resume_payload
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0193_workflow_agents"
down_revision: str | None = "0192_node_run_resume_payload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "workflow_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE", name="agents_workflow_id_fkey"),
            nullable=True,
        ),
    )
    op.add_column("agents", sa.Column("workflow_node_id", PG_UUID(as_uuid=True), nullable=True))
    op.create_check_constraint(
        "ck_agent_workflow_node", "agents", "(workflow_id IS NULL) = (workflow_node_id IS NULL)"
    )
    op.create_index(
        "uq_agents_workflow_node",
        "agents",
        ["workflow_id", "workflow_node_id"],
        unique=True,
        postgresql_where=sa.text("workflow_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agents_workflow_node", table_name="agents")
    op.drop_constraint("ck_agent_workflow_node", "agents", type_="check")
    op.drop_column("agents", "workflow_node_id")
    op.drop_column("agents", "workflow_id")
