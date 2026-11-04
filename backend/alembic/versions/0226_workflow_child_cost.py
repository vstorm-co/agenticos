"""Separate descendant spend from a workflow's own provider charges.

A caller's cap includes its called workflows, while organization-wide totals
must count each charge only once. Existing called-run spend is rolled up through
the explicit parent node links; trigger/failure chains are not calls. Keep own
spend intact so the backfill never counts a descendant twice.

Revision ID: 0226_workflow_child_cost
Revises: 0225_workflow_api_key_authority
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0226_workflow_child_cost"
down_revision: str | Sequence[str] | None = "0225_workflow_api_key_authority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("child_cost", sa.Numeric(12, 6), server_default="0", nullable=False),
    )
    op.execute("""
        WITH RECURSIVE ancestry AS (
            SELECT child.id AS child_id, step.workflow_run_id AS ancestor_id,
                   ARRAY[child.id, step.workflow_run_id] AS visited
            FROM workflow_runs child
            JOIN node_runs step ON step.id = child.parent_node_run_id
            WHERE child.id <> step.workflow_run_id
            UNION ALL
            SELECT ancestry.child_id, step.workflow_run_id,
                   ancestry.visited || step.workflow_run_id
            FROM ancestry
            JOIN workflow_runs parent ON parent.id = ancestry.ancestor_id
            JOIN node_runs step ON step.id = parent.parent_node_run_id
            WHERE NOT step.workflow_run_id = ANY(ancestry.visited)
        ), totals AS (
            SELECT ancestry.ancestor_id, SUM(child.spent_cost) AS cost,
                   BOOL_OR(child.cost_is_partial) AS partial
            FROM ancestry
            JOIN workflow_runs child ON child.id = ancestry.child_id
            GROUP BY ancestry.ancestor_id
        )
        UPDATE workflow_runs AS parent
        SET child_cost = LEAST(totals.cost, 999999.999999),
            cost_is_partial = parent.cost_is_partial OR totals.partial
                              OR totals.cost > 999999.999999
        FROM totals WHERE parent.id = totals.ancestor_id
    """)


def downgrade() -> None:
    op.drop_column("workflow_runs", "child_cost")
