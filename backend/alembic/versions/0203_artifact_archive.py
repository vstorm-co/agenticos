"""When a published page was archived.

`artifacts.archived_at` is null for a page that serves, and the time a person
archived it otherwise. An archived page keeps its versions, its grants and its
place in the agent's identity index, but no route, link or run serves it until
it is restored. Deleting was the alternative, and it is still there; archiving
is the step that can be taken back.

A timestamp rather than a flag, the shape `virtual_tables.archived_at` already
takes, so the console can say since when. A workflow's `archived` status was the
other model; a page has no status for it to join. No index:
every listing that leaves archived pages out already narrows by organization,
and the column is null on nearly every row.

No backfill: every page here serves today, and null says exactly that.

Revision ID: 0203_artifact_archive
Revises: 0202_workflow_run_public_origin
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0203_artifact_archive"
down_revision: str | None = "0202_workflow_run_public_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("artifacts", "archived_at")
