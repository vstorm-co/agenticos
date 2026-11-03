"""A sync source records the knowledge base it syncs into (#2551).

A source used to record an organization and a collection name only, and every
reader - the sync itself, a base's sources tab, its run logs, the teardown of a
deleted base - resolved the base again from the name, which is not unique. That
filed an organization base's syncs under an older personal base of the same
name, let the CLI point a source at a base nobody chose, kept a source whose
name resolved to no base of its organization syncing unfiled chunks, and left a
deleted base's sources running into whatever base kept the name.

`knowledge_base_id` is that base, set from the base a source is created on.

The backfill gives every existing source the base its sync writes into today
(`knowledge_base_repo.choose_for_collection`): the oldest base of the name in
the source's organization, else the oldest app-scoped one. A source naming a
collection that resolves to no base cannot be attributed - it was syncing
unfiled chunks into a table only other tenants' bases claim - so it keeps its
name for the operator to read, loses nothing else, and is deactivated. Its ids
are logged. Inventing a base for it would be filing one tenant's documents
under a base somebody else chose; refusing the whole upgrade would hold a
deployment back for a row whose fix is a reassignment in the console.

A source that resolves to a member's personal base while its organization
also has an org-scoped base of the name keeps the personal base - where it
synced before - and is logged too: the upgrade cannot tell a member's own
source from an organization's source that was misfiled there.

`ON DELETE SET NULL` rather than `CASCADE`: a source carries its run history
and its document claims, and a deleted base's sources are detached and
deactivated by the teardown so they can be reassigned (as since #2574). The
foreign key is a backstop behind that, and a sync refuses a source with none.

The downgrade drops the column; it does not reactivate the sources the upgrade
deactivated, because nothing records which they were but the log.

Revision ID: 0251_sync_source_knowledge_base
Revises: 0250_discord_channel
Create Date: 2026-11-03
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "0251_sync_source_knowledge_base"
down_revision: str | None = "0250_discord_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

# `choose_for_collection` in SQL: the source's own organization's bases first,
# then app-scoped ones, each oldest first. `id` breaks a tie on `created_at`.
_BACKFILL = sa.text(
    """
    UPDATE sync_sources AS s
    SET knowledge_base_id = (
        SELECT kb.id
        FROM knowledge_bases AS kb
        WHERE kb.collection_name = s.collection_name
          AND (kb.organization_id = s.organization_id OR kb.scope = 'app')
        ORDER BY
            CASE WHEN kb.organization_id = s.organization_id THEN 0 ELSE 1 END,
            kb.created_at,
            kb.id
        LIMIT 1
    )
    WHERE s.collection_name IS NOT NULL AND s.knowledge_base_id IS NULL
    """
)

_DEACTIVATE_UNATTRIBUTABLE = sa.text(
    """
    UPDATE sync_sources
    SET is_active = false
    WHERE collection_name IS NOT NULL AND knowledge_base_id IS NULL
    RETURNING id, organization_id, collection_name
    """
)


# A source the backfill filed under a member's personal base while its
# organization also has an org-scoped base of the name: the choice the sync made
# before, kept, but likely the misfiling #2551 describes.
_ON_A_PERSONAL_BASE = sa.text(
    """
    SELECT s.id, s.organization_id, s.collection_name
    FROM sync_sources AS s
    JOIN knowledge_bases AS chosen ON chosen.id = s.knowledge_base_id
    WHERE chosen.scope = 'personal'
      AND EXISTS (
          SELECT 1 FROM knowledge_bases AS org_base
          WHERE org_base.collection_name = s.collection_name
            AND org_base.organization_id = s.organization_id
            AND org_base.scope = 'org'
      )
    ORDER BY s.id
    """
)


def backfill(bind: Connection) -> list[tuple[str, str, str]]:
    """Attribute every source naming a collection; deactivate and answer the rest.

    Apart from `upgrade` so a test can run it on rows in a schema that already
    has the column. Answers `(source id, organization id, collection name)` for
    each source that could not be attributed.
    """
    bind.execute(_BACKFILL)
    rows = bind.execute(_DEACTIVATE_UNATTRIBUTABLE).all()
    return [(str(row.id), str(row.organization_id), row.collection_name) for row in rows]


def on_a_personal_base(bind: Connection) -> list[tuple[str, str, str]]:
    """Sources the backfill filed under a personal base beside an org base of the name.

    Kept where the sync wrote before, and reported for an operator to move: the
    upgrade cannot tell a member's own source from an organization's source that
    was being misfiled into the member's older base.
    """
    rows = bind.execute(_ON_A_PERSONAL_BASE).all()
    return [(str(row.id), str(row.organization_id), row.collection_name) for row in rows]


def upgrade() -> None:
    op.add_column("sync_sources", sa.Column("knowledge_base_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("sync_sources_knowledge_base_id_idx"),
        "sync_sources",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("sync_sources_knowledge_base_id_fkey"),
        "sync_sources",
        "knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
        ondelete="SET NULL",
    )
    bind = op.get_bind()
    for source_id, organization_id, collection_name in backfill(bind):
        logger.warning(
            "Sync source %s (organization %s) names collection '%s', which no knowledge "
            "base of its organization or of the deployment holds; it was deactivated. "
            "Point it at a knowledge base to sync it again.",
            source_id,
            organization_id,
            collection_name,
        )
    for source_id, organization_id, collection_name in on_a_personal_base(bind):
        logger.warning(
            "Sync source %s (organization %s) syncs '%s' into a member's personal "
            "knowledge base, while the organization has a base of that name too. It was "
            "kept where it synced before; move it if it belongs to the organization's base.",
            source_id,
            organization_id,
            collection_name,
        )


def downgrade() -> None:
    op.drop_constraint(
        op.f("sync_sources_knowledge_base_id_fkey"), "sync_sources", type_="foreignkey"
    )
    op.drop_index(op.f("sync_sources_knowledge_base_id_idx"), table_name="sync_sources")
    op.drop_column("sync_sources", "knowledge_base_id")
