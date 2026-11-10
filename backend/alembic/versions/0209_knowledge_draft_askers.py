"""Record how many people asked the questions a model's knowledge draft came from.

Revision ID: 0209_knowledge_draft_askers
Revises: 0208_improvement_deferred
An improvement session drafts a topic even when one person asked about it,
since a person reviews every draft before it is added; the wizard warns when a
draft rests on one person's questions, and this is the count it reads. Drafts
written before it record none and show no warning.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0209_knowledge_draft_askers"
down_revision: str | None = "0208_improvement_deferred"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_gap_topics", sa.Column("draft_askers", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_gap_topics", "draft_askers")
