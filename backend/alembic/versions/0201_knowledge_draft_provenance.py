"""Pin every question a draft read, not only the sources its author cited.

Revision ID: 0201_knowledge_draft_provenance
Revises: 0200_improvement_retained_cost
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0201_knowledge_draft_provenance"
down_revision: str | None = "0200_improvement_retained_cost"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing drafts did not record uncited inputs. NULL means untracked;
    # backfilling from today's surviving members would invent provenance.
    op.add_column(
        "knowledge_gap_topics",
        sa.Column(
            "draft_evidence_run_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True
        ),
    )
    op.add_column(
        "knowledge_gap_topics",
        sa.Column("draft_evidence_input_hashes", postgresql.ARRAY(sa.String(64)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_gap_topics", "draft_evidence_input_hashes")
    op.drop_column("knowledge_gap_topics", "draft_evidence_run_ids")
