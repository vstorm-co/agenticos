"""Keep a skill check's families of criteria on each agent's row.

An agent of a skill check is judged on its families of criteria - every case's check
of one thing counted together, case by case - but only its single criteria were
kept, so the row listed one line per case's check. `skill_check_agents` gains
`families`, each family's counts over the agent's held-out questions. A row judged
before this revision keeps an empty list.

The downgrade drops the column.

Revision ID: 0350_skill_check_families
Revises: 0349_personal_work_context
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0350_skill_check_families"
down_revision: str = "0349_personal_work_context"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "skill_check_agents",
        sa.Column(
            "families",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("skill_check_agents", "families")
