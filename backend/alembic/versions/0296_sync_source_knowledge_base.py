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
deployment back for a row whose fix is a reassignment in the console. So is a
source whose name two bases tie for first on: the earlier code ordered them by
`created_at` alone and picked neither in particular, and resolving the name
again would guess the same way, so its log says to add it again from the right
base.

A source that resolves to a member's personal base while its organization
also has an org-scoped base of the name keeps the personal base - where it
synced before - and is logged too: the upgrade cannot tell a member's own
source from an organization's source that was misfiled there.

`ON DELETE SET NULL` rather than `CASCADE`: a source carries its run history
and its document claims, and a deleted base's sources are detached and
deactivated by the teardown so they can be reassigned (as since #2574). The
foreign key is a backstop behind that, and a sync refuses a source with none.

The downgrade drops the column; it does not reactivate the sources the upgrade
deactivated, because nothing records which they were but the log. Before it
drops the column it deactivates, and logs with the reason, every active source
naming a collection that records no base, or a base other than the single one
its name resolves to: the earlier code would sync it by name instead. That stops
its scheduled syncs; the earlier code's manual sync does not check `is_active`.

Revision ID: 0296_sync_source_knowledge_base
Revises: 0295_tool_approval_consent
Create Date: 2026-11-03
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "0296_sync_source_knowledge_base"
down_revision: str | None = "0295_tool_approval_consent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

# `choose_for_collection` in SQL, for the source `s`: its own organization's
# bases first, then app-scoped ones, each oldest first - or NULL when none holds
# the name, or two bases tie for first. The code before this revision orders
# only by `created_at`, so a tie (two bases inserted in one transaction share
# `now()`) had no defined winner; a source is not pinned to a guess at it.
# Which bases may hold the source `s`: its own organization's, of any scope, and
# app-scoped ones. Never another organization's, nor a personal base of none.
_CANDIDATE = """kb.collection_name = s.collection_name
              AND (kb.organization_id = s.organization_id OR kb.scope = 'app')"""

_LEGACY_CHOICE = f"""(
        SELECT CASE WHEN count(*) = 1 THEN (array_agg(ranked.id))[1] END
        FROM (
            SELECT kb.id, rank() OVER (
                ORDER BY
                    CASE WHEN kb.organization_id = s.organization_id THEN 0 ELSE 1 END,
                    kb.created_at
            ) AS place
            FROM knowledge_bases AS kb
            WHERE {_CANDIDATE}
        ) AS ranked
        WHERE ranked.place = 1
    )"""

_BACKFILL = sa.text(
    f"""
    UPDATE sync_sources AS s
    SET knowledge_base_id = {_LEGACY_CHOICE}
    WHERE s.collection_name IS NOT NULL AND s.knowledge_base_id IS NULL
    """
)

# `ambiguous`: some base holds the name, but two tie for first.
_DEACTIVATE_UNATTRIBUTABLE = sa.text(
    f"""
    UPDATE sync_sources AS s
    SET is_active = false
    WHERE s.collection_name IS NOT NULL AND s.knowledge_base_id IS NULL AND s.is_active
    RETURNING s.id, s.organization_id, s.collection_name, EXISTS (
        SELECT 1 FROM knowledge_bases AS kb WHERE {_CANDIDATE}
    ) AS ambiguous
    """
)


# What a downgrade must not leave running: an active source naming a collection
# that records no base (the foreign key's `SET NULL` fired: this revision never
# syncs it, the earlier code would), or a base other than the one the name
# resolves to - or any base, when the name has no single answer. The code
# before this revision resolves the name, so it would sync that source into
# another base, and another audience. Only the column holds the choice, and the
# downgrade drops it. `reason` says which of the three it was.
_DEACTIVATE_DIVERGING = sa.text(
    f"""
    UPDATE sync_sources AS s
    SET is_active = false
    WHERE s.is_active
      AND s.collection_name IS NOT NULL
      AND (
          s.knowledge_base_id IS NULL
          OR s.knowledge_base_id IS DISTINCT FROM {_LEGACY_CHOICE}
      )
    RETURNING s.id, s.organization_id, s.collection_name, CASE
        WHEN s.knowledge_base_id IS NULL THEN 'unpinned'
        WHEN {_LEGACY_CHOICE} IS NULL THEN 'unresolved'
        ELSE 'elsewhere'
    END AS reason
    """
)

_STOPPED_BECAUSE = {
    "unpinned": "records no knowledge base; without this revision it would sync "
    "collection '%s' by name",
    "unresolved": "records a knowledge base, but collection '%s' resolves to no single "
    "base without this revision",
    "elsewhere": "records a knowledge base other than the one collection '%s' resolves "
    "to without this revision",
}


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


def backfill(bind: Connection) -> list[tuple[str, str, str, bool]]:
    """Attribute every source naming a collection; deactivate and answer the rest.

    Apart from `upgrade` so a test can run it on rows in a schema that already
    has the column. Answers `(source id, organization id, collection name,
    ambiguous)` for each active source that could not be attributed and was
    deactivated - `ambiguous` when bases hold the name but two tie for first;
    one already inactive stays so, unreported.
    """
    bind.execute(_BACKFILL)
    rows = bind.execute(_DEACTIVATE_UNATTRIBUTABLE).all()
    return [
        (str(row.id), str(row.organization_id), row.collection_name, row.ambiguous) for row in rows
    ]


def on_a_personal_base(bind: Connection) -> list[tuple[str, str, str]]:
    """Sources the backfill filed under a personal base beside an org base of the name.

    Kept where the sync wrote before, and reported for an operator to move: the
    upgrade cannot tell a member's own source from an organization's source that
    was being misfiled into the member's older base.
    """
    rows = bind.execute(_ON_A_PERSONAL_BASE).all()
    return [(str(row.id), str(row.organization_id), row.collection_name) for row in rows]


def deactivate_diverging(bind: Connection) -> list[tuple[str, str, str, str]]:
    """Deactivate active sources the earlier code would sync into another base.

    Apart from `downgrade` so a test can run it while the column still exists.
    Answers `(source id, organization id, collection name, reason)` for each:
    `unpinned` when it records no base, `unresolved` when its name has no single
    base, `elsewhere` when the name resolves to a base other than its own.
    """
    rows = bind.execute(_DEACTIVATE_DIVERGING).all()
    return [
        (str(row.id), str(row.organization_id), row.collection_name, row.reason) for row in rows
    ]


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
    for source_id, organization_id, collection_name, ambiguous in backfill(bind):
        # Re-pointing by name resolves a tie the same undefined way, so a tied
        # source is added again from its base, which records that base by id.
        logger.warning(
            "Sync source %s (organization %s) names collection '%s', which %s; it was "
            "deactivated. %s",
            source_id,
            organization_id,
            collection_name,
            "two knowledge bases created at the same moment hold equally"
            if ambiguous
            else "no knowledge base of its organization or of the deployment holds",
            "Add it again from the Sync tab of the base it belongs to, then delete it."
            if ambiguous
            else "Point it at a knowledge base and set is_active back to true to sync it again.",
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
    for source_id, organization_id, collection_name, reason in deactivate_diverging(op.get_bind()):
        logger.warning(
            "Sync source %s (organization %s) %s, so it was deactivated. That stops only "
            "its scheduled syncs: a manual sync still resolves the name. Re-point it "
            "before syncing it again.",
            source_id,
            organization_id,
            _STOPPED_BECAUSE[reason] % collection_name,
        )
    op.drop_constraint(
        op.f("sync_sources_knowledge_base_id_fkey"), "sync_sources", type_="foreignkey"
    )
    op.drop_index(op.f("sync_sources_knowledge_base_id_idx"), table_name="sync_sources")
    op.drop_column("sync_sources", "knowledge_base_id")
