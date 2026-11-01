"""Allow one called run per `workflow.run` step, and sum stored file bytes from an index.

A `workflow.run` step looks for the run it called and, finding none, admits one.
A step re-dispatched while its first attempt was still admitting could admit a
second, so the link from a run to the step that called it is unique. A step that
already has more than one child (the window above) keeps the oldest as its call;
the others stay as ordinary runs with no parent.

The file quota sums `workflow_files.byte_size` for an organization on every save, so
an index on the organization that carries the size lets the sum read the index alone.

Revision ID: 0223_workflow_call_unique
Revises: 0222_workflow_run_impersonated
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0223_workflow_call_unique"
down_revision: str | Sequence[str] | None = "0222_workflow_run_impersonated"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE workflow_runs SET parent_node_run_id = NULL
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY parent_node_run_id ORDER BY created_at, id
                ) AS position
                FROM workflow_runs WHERE parent_node_run_id IS NOT NULL
            ) AS ranked WHERE position > 1
        )
        """
    )
    op.drop_index("workflow_runs_parent_node_run_id_idx", table_name="workflow_runs")
    op.create_index(
        "uq_workflow_run_parent_node_run",
        "workflow_runs",
        ["parent_node_run_id"],
        unique=True,
        postgresql_where="parent_node_run_id IS NOT NULL",
    )
    op.create_index(
        "ix_workflow_file_org_bytes",
        "workflow_files",
        ["organization_id"],
        postgresql_include=["byte_size"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_file_org_bytes", table_name="workflow_files")
    op.drop_index("uq_workflow_run_parent_node_run", table_name="workflow_runs")
    op.create_index("workflow_runs_parent_node_run_id_idx", "workflow_runs", ["parent_node_run_id"])
