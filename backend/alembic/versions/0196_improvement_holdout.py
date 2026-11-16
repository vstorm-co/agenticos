"""Freeze train/holdout membership by case identity, including older revisions.

Revision ID: 0196_improvement_holdout
Revises: 0195_system_agent_choices
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0196_improvement_holdout"
down_revision: str | None = "0195_system_agent_choices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "improvement_runs",
        sa.Column(
            "chat_evidence_run_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True
        ),
    )
    op.add_column(
        "datasets",
        sa.Column(
            "improvement_holdout_share", sa.Numeric(4, 3), nullable=False, server_default="0.5"
        ),
    )
    op.create_check_constraint(
        "ck_dataset_improvement_holdout_share",
        "datasets",
        "improvement_holdout_share BETWEEN 0 AND 1",
    )
    op.add_column("dataset_cases", sa.Column("improvement_partition", sa.String(7), nullable=True))
    # UUID text and the first 32 MD5 bits are the same as the runtime assignment.
    # Membership depends on identity, so every historical revision stays in one part.
    op.execute("""UPDATE dataset_cases SET improvement_partition = CASE
        WHEN ('x' || substr(md5(case_id::text), 1, 8))::bit(32)::bigint < 2147483648
        THEN 'holdout' ELSE 'train' END""")
    op.alter_column("dataset_cases", "improvement_partition", nullable=False)
    op.create_check_constraint(
        "ck_dataset_case_improvement_partition",
        "dataset_cases",
        "improvement_partition IN ('train', 'holdout')",
    )


def downgrade() -> None:
    op.drop_column("improvement_runs", "chat_evidence_run_ids")
    op.drop_constraint("ck_dataset_case_improvement_partition", "dataset_cases", type_="check")
    op.drop_column("dataset_cases", "improvement_partition")
    op.drop_constraint("ck_dataset_improvement_holdout_share", "datasets", type_="check")
    op.drop_column("datasets", "improvement_holdout_share")
