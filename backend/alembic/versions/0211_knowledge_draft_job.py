"""Remember the job writing a knowledge gap topic's draft.

Revision ID: 0211_knowledge_draft_job
Revises: 0210_improvement_drop_triage
A topic is drafted only when a person asks, in a background job; the topic
keeps the newest one so its page shows the draft being written, or failed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0211_knowledge_draft_job"
down_revision: str | None = "0210_improvement_drop_triage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_gap_topics",
        sa.Column("draft_job_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "knowledge_gap_topics_draft_job_id_fkey",
        "knowledge_gap_topics",
        "background_jobs",
        ["draft_job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "knowledge_gap_topics_draft_job_id_fkey", "knowledge_gap_topics", type_="foreignkey"
    )
    op.drop_column("knowledge_gap_topics", "draft_job_id")
