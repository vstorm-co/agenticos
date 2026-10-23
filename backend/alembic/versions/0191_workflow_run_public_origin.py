"""Whether an outsider is behind each workflow run's chain.

`workflow_runs.public_origin` is true for a run an outsider started through a
door - a webhook, a form, a channel message, an email, a repository event - and
for every run under one: a called child, a failure's run, a table run fired by a
record a run with no person wrote, and the retry of any of them. An agent step
in such a run has no person behind it.

It is stored, rather than read from the chain's root, because a table run fired
by a run's write and a retry are each a root of their own: nothing else on their
row says where they came from. A new `triggered_by` value was the alternative;
it would have reached the graph through `core.input` and every trigger label.

The backfill marks each public root and every run whose root is one. Two kinds
of run already here cannot be recovered and stay false: a table run fired by a
write that a run with no person made, and the retry of a public child.

Revision ID: 0191_workflow_run_public_origin
Revises: 0190_artifact_bindings
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0191_workflow_run_public_origin"
down_revision: str | None = "0190_artifact_bindings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("public_origin", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # A root's `root_run_id` is its own id, so this marks the public roots too.
    op.execute(
        "UPDATE workflow_runs AS r SET public_origin = true "
        "FROM workflow_runs AS root "
        "WHERE root.id = r.root_run_id "
        "AND root.triggered_by IN ('webhook', 'form', 'channel_message', 'gmail', 'github')"
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "public_origin")
