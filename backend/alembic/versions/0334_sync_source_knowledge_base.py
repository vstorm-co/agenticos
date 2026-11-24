"""Pin sync sources to the knowledge base their previous runs resolved (#2551).

Backfill the current name resolver exactly: prefer the source organization's
bases, then app-scoped bases, ordered by creation time and id. Timestamp ties
have a deterministic winner and must not deactivate a working source.

Sources with no eligible base are deactivated and logged. A source left on a
member's personal base beside an org base of the same name is preserved and
reported, because its intended owner cannot be inferred from its old name.

Deleting a base detaches and deactivates its sources. ON DELETE SET NULL is the
foreign-key backstop; unassigned sources cannot sync. Downgrade deactivates any
source the old name resolver would send elsewhere, retaining paused sources.
Operators must reassign and reactivate these sources before syncing again.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "0334_sync_source_knowledge_base"
down_revision: str | None = "0333_channel_thread_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

# Match the deployed resolver's tenant preference and deterministic tie-break.
_CANDIDATE = """kb.collection_name = s.collection_name
              AND (kb.organization_id = s.organization_id OR kb.scope = 'app')"""

_LEGACY_CHOICE = f"""(
        SELECT kb.id
        FROM knowledge_bases AS kb
        WHERE {_CANDIDATE}
        ORDER BY CASE WHEN kb.organization_id = s.organization_id THEN 0 ELSE 1 END,
                 kb.created_at, kb.id
        LIMIT 1
    )"""

_BACKFILL = sa.text(
    f"""
    UPDATE sync_sources AS s
    SET knowledge_base_id = {_LEGACY_CHOICE}
    WHERE s.collection_name IS NOT NULL AND s.knowledge_base_id IS NULL
    """
)

_DEACTIVATE_UNATTRIBUTABLE = sa.text(
    """
    UPDATE sync_sources AS s
    SET is_active = false
    WHERE s.collection_name IS NOT NULL AND s.knowledge_base_id IS NULL AND s.is_active
    RETURNING s.id, s.organization_id, s.collection_name
    """
)


# What a downgrade must not leave running: an active source naming a collection
# that records no base (the foreign key's `SET NULL` fired: this revision never
# syncs it, the earlier code would), or a base other than the one the name
# resolves to - or any base, when the name has no eligible answer. The code
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
    "unresolved": "records a knowledge base, but collection '%s' resolves to no eligible "
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


def backfill(bind: Connection) -> list[tuple[str, str, str]]:
    """Pin legacy sources; report active sources stopped for lacking a target."""
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


def deactivate_diverging(bind: Connection) -> list[tuple[str, str, str, str]]:
    """Deactivate active sources the earlier code would sync into another base.

    Apart from `downgrade` so a test can run it while the column still exists.
    Answers `(source id, organization id, collection name, reason)` for each:
    `unpinned` when it records no base, `unresolved` when its name has no eligible
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
    for source_id, organization_id, collection_name in backfill(bind):
        logger.warning(
            "Sync source %s (organization %s) names collection '%s', which no knowledge "
            "base of its organization or of the deployment holds; it was deactivated. "
            "Point it at a knowledge base and set is_active back to true to sync it again.",
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
    for source_id, organization_id, collection_name, reason in deactivate_diverging(op.get_bind()):
        logger.warning(
            "Sync source %s (organization %s) %s, so it was deactivated. That stops only "
            "new syncs. Re-point and reactivate it before syncing it again.",
            source_id,
            organization_id,
            _STOPPED_BECAUSE[reason] % collection_name,
        )
    op.drop_constraint(
        op.f("sync_sources_knowledge_base_id_fkey"), "sync_sources", type_="foreignkey"
    )
    op.drop_index(op.f("sync_sources_knowledge_base_id_idx"), table_name="sync_sources")
    op.drop_column("sync_sources", "knowledge_base_id")
