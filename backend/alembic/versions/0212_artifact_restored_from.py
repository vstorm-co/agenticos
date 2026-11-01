"""Which version a restored page version was copied from.

Restoring version N of a page adds a new version carrying N's bytes, so the
history stays append-only. Until now nothing on that new version said so: in the
picker it read like any other publication, with no run behind it.
`artifact_versions.restored_from` holds N's number for a version a restore made,
and is null for every version a run published.

A number rather than a foreign key to the source row: kept versions are pruned
past a window, and the note should outlive the version it names - "restored from
v2" stays true after v2 is gone. A key would have to be `SET NULL` and lose
exactly that. No index: it is only ever read with the row it sits on.

No backfill: the audit log's `artifact.version_restored` entries name past
restores, but a version list that suddenly gained notes for some of them and not
others (pruned rows, swept audit entries) would be less honest than none. Earlier
restores read as plain versions, as they did.

Revision ID: 0212_artifact_restored_from
Revises: 0211_artifact_archive
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0212_artifact_restored_from"
down_revision: str | None = "0211_artifact_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("artifact_versions", sa.Column("restored_from", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("artifact_versions", "restored_from")
