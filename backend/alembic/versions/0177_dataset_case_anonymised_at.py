"""When a dataset case's text was anonymised after its person was erased (#2373).

Erasing a person replaces the text of every case taken from their conversations
or runs, in every revision that held it, so a revision is no longer immutable in
that one respect. The timestamp marks what happened, so the case reads as
anonymised rather than as a case somebody wrote that way, and an eval run leaves
it out until its curator rewrites it. A downgrade drops the mark, and the
placeholder text stays.

Revision ID: 0177_dataset_case_anonymised_at
Revises: 0173_eval_job_pool
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0177_dataset_case_anonymised_at"
down_revision: str | None = "0173_eval_job_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dataset_cases",
        sa.Column("anonymised_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dataset_cases", "anonymised_at")
