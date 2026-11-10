"""Remember which system agents were selected where their work is requested.

Revision ID: 0195_system_agent_choices
Revises: 0194_improvement_pipeline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0195_system_agent_choices"
down_revision: str | None = "0194_improvement_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("case_generations", "generator_agent_id"),
    ("authoring_requests", "improver_agent_id"),
    ("improvement_runs", "improver_agent_id"),
    ("knowledge_bases", "gap_drafter_agent_id"),
    ("knowledge_bases", "gap_classifier_agent_id"),
)


def upgrade() -> None:
    # Deliberately retained identities: deleting a selected agent must refuse
    # with a missing-agent reason rather than quietly change the chosen helper.
    for table, column in _COLUMNS:
        op.add_column(table, sa.Column(column, postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    for table, column in reversed(_COLUMNS):
        op.drop_column(table, column)
