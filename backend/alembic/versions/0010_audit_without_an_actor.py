"""An audit entry the platform wrote itself

Revision ID: 0010_audit_without_an_actor
Revises: 0009_align_index_names
Create Date: 2026-08-06

`actor_user_id` was `NOT NULL` because every action the log recorded arrived
from a person: an admin promoting somebody, a share granted, a skill published.
The approval expiry sweep is the first that does not. Nobody decided - that is
precisely what it records - so there is no id to put in the column, and the two
alternatives are worse than a null: writing the run's owner asserts a decision
they did not make, and writing nothing at all leaves the one approvals outcome
with no trail behind it.

So null here means "the platform, on a schedule", and it is the only thing it
can mean: every caller with an actor still passes one, and a null cannot be
produced by an authenticated path.

No backfill and no default. Every existing row was written by a person and
already names them.

Irreversible in one direction only, which is why the downgrade deletes rather
than fails: restoring `NOT NULL` with actorless rows present would abort the
migration outright and leave a deployment unable to go back at all. The rows it
removes are expiry entries, whose facts are still on the `tool_approvals` rows
themselves - `status = 'expired'`, `decided_by_user_id IS NULL`, `decided_at`.
The trail thins; it does not disappear.
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_audit_without_an_actor"
down_revision = "0009_align_index_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "app_admin_audit_logs",
        "actor_user_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("DELETE FROM app_admin_audit_logs WHERE actor_user_id IS NULL")
    op.alter_column(
        "app_admin_audit_logs",
        "actor_user_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
