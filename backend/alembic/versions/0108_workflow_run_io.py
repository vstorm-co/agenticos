"""Give a workflow run the input it was started with and the answer it gave (#1789).

`core.input` hands the graph what the invoking surface supplied, and `core.output`
records what the run answers. Neither existed while every graph was a chain of
debug nodes, so a run had nowhere to keep either: the input has to survive a
restart - a node dispatched after one reads the payload the run was admitted
with - and the output is what an adapter delivers back to the caller (#1792).

`input` is `NOT NULL` with an empty-object default, so a run admitted before this
revision reads as having been started with nothing, which is what it was.
`output` is nullable: a run that has not answered, or whose graph has no output
node, has no answer.

Revision ID: 0108_workflow_run_io
Revises: 0107_workflow_run_node_count
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0108_workflow_run_io"
down_revision: str | Sequence[str] | None = "0107_workflow_run_node_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "output")
    op.drop_column("workflow_runs", "input")
