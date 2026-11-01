"""Datasets name the agent they test; a generation may accept its own drafts.

An agent's test set is built for it without a person choosing each case, and
found again by the agent rather than by a name somebody may change, so
`datasets.agent_id` records the agent a dataset was made to test - nullable, as
every dataset made by hand names none, and cleared when the agent goes.

`case_generations.auto_accept` marks a generation whose drafts become a version
as soon as they are ready - only that test set's - where every other generation
waits for a person to accept each draft. Both start empty for the rows already
there, which is what they were.

Revision ID: 0181_dataset_agent_auto_accept
Revises: 0179_case_generation_drop_counts
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0181_dataset_agent_auto_accept"
down_revision: str | None = "0179_case_generation_drop_counts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("agent_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("datasets_agent_id_fkey"),
        "datasets",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("datasets_agent_id_idx"), "datasets", ["agent_id"])
    op.add_column(
        "case_generations",
        sa.Column("auto_accept", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("case_generations", "auto_accept")
    op.drop_index(op.f("datasets_agent_id_idx"), table_name="datasets")
    op.drop_constraint(op.f("datasets_agent_id_fkey"), "datasets", type_="foreignkey")
    op.drop_column("datasets", "agent_id")
