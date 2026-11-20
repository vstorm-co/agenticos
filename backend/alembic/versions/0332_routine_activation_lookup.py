"""Index exact routine activations independently of paginated history.

A partial expression index leaves legacy policies untouched and makes polling
one UUID a point lookup. Like other transactional index migrations here, the
build briefly holds writes until upgrade commits; a failed upgrade rolls back
completely. Downgrade removes only the index, preserving all run provenance.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0332_routine_activation_lookup"
down_revision: str = "0331_routine_overlap_attempt"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_index(
        "ix_agent_runs_routine_activation",
        "agent_runs",
        ["organization_id", sa.text("(routine_policy ->> 'activation_id')")],
        postgresql_where=sa.text("(routine_policy ->> 'activation_id') IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_routine_activation", table_name="agent_runs")
