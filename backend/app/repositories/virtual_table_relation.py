"""Relationship persistence scoped to one organization and source table.

Record writes keep their JSONB representation for existing readers and immutable
history. The constrained edge set is replaced in the same transaction, under the
record lock; reverse traversal and relational predicates use that set. Historical
unresolvable values are retained separately rather than becoming invalid edges.
"""

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import ColumnElement, and_, delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.virtual_table import VirtualTable, VirtualTableRecord
from app.db.models.virtual_table_relation import (
    VirtualTableLinkEvidence,
    VirtualTableRecordLink,
    VirtualTableRelation,
)

EvidenceReason = Literal[
    "invalid_cell", "invalid_id", "missing_target", "duplicate_target", "limit_exceeded"
]


@dataclass(frozen=True)
class LinkEvidence:
    position: int
    reason: EvidenceReason
    value: JsonValue


@dataclass(frozen=True)
class LinkPlan:
    links: tuple[tuple[int, UUID], ...]
    evidence: tuple[LinkEvidence, ...]


def plan_links(value: JsonValue, targets: set[UUID], *, max_links: int = 100) -> LinkPlan:
    """Separate valid ordered links from retained evidence without repairing data.

    Target IDs are those found in the declared destination table and organization.
    Invalid whole cells are held intact. Duplicates and missing IDs retain their
    original positions, so reconstruction does not depend on what was discarded.
    """
    if value is None:
        return LinkPlan((), ())
    if not isinstance(value, list):
        return LinkPlan((), (LinkEvidence(-1, "invalid_cell", value),))
    if len(value) > max_links:
        return LinkPlan((), (LinkEvidence(-1, "limit_exceeded", value),))
    links: list[tuple[int, UUID]] = []
    evidence: list[LinkEvidence] = []
    seen: set[UUID] = set()
    for position, item in enumerate(value):
        try:
            record_id = UUID(item) if isinstance(item, str) else None
        except ValueError:
            record_id = None
        if record_id is None:
            evidence.append(LinkEvidence(position, "invalid_id", item))
        elif record_id in seen:
            evidence.append(LinkEvidence(position, "duplicate_target", item))
        elif record_id not in targets:
            evidence.append(LinkEvidence(position, "missing_target", item))
            seen.add(record_id)
        else:
            links.append((len(links), record_id))
            seen.add(record_id)
    return LinkPlan(tuple(links), tuple(evidence))


async def sync_schema(
    db: AsyncSession, *, table_id: UUID, columns: Sequence[Mapping[str, object]]
) -> None:
    """Persist the current definitions while the caller holds the schema lock."""
    organization_id = await db.scalar(
        select(VirtualTable.organization_id).where(VirtualTable.id == table_id)
    )
    if organization_id is None:
        raise ValueError("A relationship schema requires an existing source table")
    await db.execute(
        update(VirtualTableRelation)
        .where(
            VirtualTableRelation.organization_id == organization_id,
            VirtualTableRelation.source_table_id == table_id,
        )
        .values(archived=True)
    )
    for column in columns:
        if column.get("type") != "link":
            continue
        statement = pg_insert(VirtualTableRelation).values(
            organization_id=organization_id,
            source_table_id=table_id,
            column_id=UUID(str(column["id"])),
            target_table_id=UUID(str(column["link_table_id"])),
            archived=bool(column.get("archived", False)),
            max_links=column.get("link_limit") or 100,
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=["organization_id", "source_table_id", "column_id"],
                set_={
                    "target_table_id": statement.excluded.target_table_id,
                    "archived": statement.excluded.archived,
                    "max_links": statement.excluded.max_links,
                },
            )
        )
    await db.flush()


async def definitions(
    db: AsyncSession, *, organization_id: UUID, source_table_id: UUID
) -> list[VirtualTableRelation]:
    result = await db.scalars(
        select(VirtualTableRelation)
        .where(
            VirtualTableRelation.organization_id == organization_id,
            VirtualTableRelation.source_table_id == source_table_id,
        )
        .execution_options(populate_existing=True)
    )
    return list(result)


async def largest_link_count(
    db: AsyncSession, *, organization_id: UUID, table_id: UUID, column_id: UUID
) -> int:
    """Maximum active cardinality, including valid links hidden from the caller."""
    counts = (
        select(func.count().label("n"))
        .where(
            VirtualTableRecordLink.organization_id == organization_id,
            VirtualTableRecordLink.source_table_id == table_id,
            VirtualTableRecordLink.column_id == column_id,
        )
        .group_by(VirtualTableRecordLink.source_record_id)
        .subquery()
    )
    result = await db.scalar(select(func.coalesce(func.max(counts.c.n), 0)))
    return int(result or 0)


def _evidence_key(position: int, reason: str, value: JsonValue) -> tuple[int, str, str]:
    return position, reason, json.dumps(value, sort_keys=True, ensure_ascii=False)


async def sync_record(db: AsyncSession, *, record: VirtualTableRecord) -> None:
    """Replace one locked record's edge set without changing its revision/history.

    Visibility is deliberately not checked here: preserved hidden links are part
    of internal storage. The service validates the caller's requested changes.
    Foreign-key constraints independently enforce organization and endpoint bounds.
    """
    relations = await definitions(
        db, organization_id=record.organization_id, source_table_id=record.table_id
    )
    if not relations:
        return
    candidates: set[UUID] = set()
    for relation in relations:
        value = record.values.get(str(relation.column_id))
        if isinstance(value, list) and len(value) <= relation.max_links:
            for item in value:
                if isinstance(item, str):
                    try:
                        candidates.add(UUID(item))
                    except ValueError:
                        continue
    found = await db.execute(
        select(VirtualTableRecord.table_id, VirtualTableRecord.id).where(
            VirtualTableRecord.organization_id == record.organization_id,
            VirtualTableRecord.id.in_(candidates),
        )
    )
    targets: dict[UUID, set[UUID]] = {}
    for table_id, record_id in found:
        targets.setdefault(table_id, set()).add(record_id)
    held = await db.scalars(
        select(VirtualTableLinkEvidence).where(
            VirtualTableLinkEvidence.organization_id == record.organization_id,
            VirtualTableLinkEvidence.source_table_id == record.table_id,
            VirtualTableLinkEvidence.source_record_id == record.id,
        )
    )
    retained = {
        (row.column_id, *_evidence_key(row.position, row.reason, row.value)) for row in held
    }
    await db.execute(
        delete(VirtualTableRecordLink).where(
            VirtualTableRecordLink.organization_id == record.organization_id,
            VirtualTableRecordLink.source_table_id == record.table_id,
            VirtualTableRecordLink.source_record_id == record.id,
        )
    )
    for relation in relations:
        plan = plan_links(
            cast(JsonValue, record.values.get(str(relation.column_id))),
            targets.get(relation.target_table_id, set()),
            max_links=relation.max_links,
        )
        for position, target_id in plan.links:
            db.add(
                VirtualTableRecordLink(
                    organization_id=record.organization_id,
                    source_table_id=record.table_id,
                    source_record_id=record.id,
                    column_id=relation.column_id,
                    target_table_id=relation.target_table_id,
                    target_record_id=target_id,
                    position=position,
                    max_links=relation.max_links,
                )
            )
        for item in plan.evidence:
            key = (relation.column_id, *_evidence_key(item.position, item.reason, item.value))
            if key in retained:
                continue
            db.add(
                VirtualTableLinkEvidence(
                    organization_id=record.organization_id,
                    source_table_id=record.table_id,
                    source_record_id=record.id,
                    column_id=relation.column_id,
                    source_revision=record.revision,
                    position=item.position,
                    reason=item.reason,
                    value=item.value,
                )
            )
    await db.flush()


def contains_targets(column_id: UUID, target_ids: Collection[UUID]) -> ColumnElement[bool]:
    """A correlated link predicate; the surrounding record query owns authorization."""
    return exists(
        select(VirtualTableRecordLink.target_record_id)
        .where(
            VirtualTableRecordLink.organization_id == VirtualTableRecord.organization_id,
            VirtualTableRecordLink.source_table_id == VirtualTableRecord.table_id,
            VirtualTableRecordLink.source_record_id == VirtualTableRecord.id,
            VirtualTableRecordLink.column_id == column_id,
            VirtualTableRecordLink.target_record_id.in_(target_ids),
        )
        .correlate(VirtualTableRecord.__table__)
    )


async def linked_ids(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    revisions: Mapping[UUID, int | None],
    column_ids: Sequence[UUID],
) -> dict[UUID, dict[UUID, list[str]]]:
    """Ordered canonical IDs, including empty cells for every declared requested link.

    This is internal storage, not an authorized public projection. Callers still
    filter target records through the common linked-table/row access checks. A
    receipt or concurrent read may hold an earlier source revision; leave that
    immutable snapshot intact rather than mixing current links into an old row.
    """
    result: dict[UUID, dict[UUID, list[str]]] = {}
    rows = await db.execute(
        select(
            VirtualTableRecord.id,
            VirtualTableRecord.revision,
            VirtualTableRecordLink.column_id,
            VirtualTableRecordLink.target_record_id,
        )
        .outerjoin(
            VirtualTableRecordLink,
            and_(
                VirtualTableRecordLink.organization_id == VirtualTableRecord.organization_id,
                VirtualTableRecordLink.source_table_id == VirtualTableRecord.table_id,
                VirtualTableRecordLink.source_record_id == VirtualTableRecord.id,
                VirtualTableRecordLink.column_id.in_(column_ids),
            ),
        )
        .where(
            VirtualTableRecord.organization_id == organization_id,
            VirtualTableRecord.table_id == table_id,
            VirtualTableRecord.id.in_(revisions),
        )
        .order_by(VirtualTableRecordLink.position)
    )
    for record_id, revision, column_id, target_id in rows:
        if revisions[record_id] is not None and revisions[record_id] != revision:
            continue
        cells = result.setdefault(record_id, {key: [] for key in column_ids})
        if column_id is not None:
            cells[column_id].append(str(target_id))
    return result


async def write_values(
    db: AsyncSession, *, record: VirtualTableRecord, column_ids: Sequence[UUID]
) -> dict[str, Any]:
    """Canonical baseline for a locked source write, including hidden valid links.

    Callers retain the original record values for history. Invalid legacy values
    remain in evidence and original storage until a real edit replaces that
    storage representation; a no-op must compare to this baseline instead.
    """
    values = dict(record.values)
    if not column_ids:
        return values
    canonical = await linked_ids(
        db,
        organization_id=record.organization_id,
        table_id=record.table_id,
        revisions={record.id: record.revision},
        column_ids=column_ids,
    )
    values.update(
        {
            str(key): ids
            for key, ids in canonical.get(record.id, {}).items()
            if ids or str(key) in values
        }
    )
    return values


async def get_definition(
    db: AsyncSession,
    *,
    organization_id: UUID,
    source_table_id: UUID,
    column_id: UUID,
    target_table_id: UUID,
) -> VirtualTableRelation | None:
    return await db.scalar(
        select(VirtualTableRelation)
        .where(
            and_(
                VirtualTableRelation.organization_id == organization_id,
                VirtualTableRelation.source_table_id == source_table_id,
                VirtualTableRelation.column_id == column_id,
                VirtualTableRelation.target_table_id == target_table_id,
                VirtualTableRelation.archived.is_(False),
            )
        )
        .execution_options(populate_existing=True)
    )
