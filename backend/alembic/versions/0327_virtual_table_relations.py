"""Normalize virtual-table links without rewriting record history.

Revision ID: 0327_virtual_table_relations
Revises: 0326_room_threads

This migration requires a complete Tables read/write outage: the composite
record uniqueness constraint holds ACCESS EXCLUSIVE through the backfill.
Stop Tables traffic, migrate, then start only the new application version.
Old application versions do not maintain the new edges.
Malformed, duplicate and dangling values are retained as repair evidence.
"""

from collections.abc import Sequence
from typing import Any, TypedDict
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0327_virtual_table_relations"
down_revision: str | None = "0326_room_threads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _Definition(TypedDict):
    organization_id: UUID
    source_table_id: UUID
    column_id: UUID
    target_table_id: UUID
    archived: bool
    max_links: int


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_virtual_table_record_org_table_id",
        "virtual_table_records",
        ["organization_id", "table_id", "id"],
    )
    op.create_table(
        "virtual_table_relations",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_table_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_table_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("max_links", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("organization_id", "source_table_id", "column_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            name="virtual_table_relations_source_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "target_table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            name="virtual_table_relations_target_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "source_table_id",
            "column_id",
            "target_table_id",
            "max_links",
            name="uq_virtual_table_relation_target",
        ),
        sa.CheckConstraint("max_links BETWEEN 1 AND 100", name="max_links"),
    )
    op.create_index(
        "virtual_table_relations_target_idx",
        "virtual_table_relations",
        ["organization_id", "target_table_id"],
    )
    op.create_table(
        "virtual_table_record_links",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_table_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_table_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("max_links", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "source_table_id",
            "column_id",
            "source_record_id",
            "target_record_id",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_table_id", "column_id", "target_table_id", "max_links"],
            [
                "virtual_table_relations.organization_id",
                "virtual_table_relations.source_table_id",
                "virtual_table_relations.column_id",
                "virtual_table_relations.target_table_id",
                "virtual_table_relations.max_links",
            ],
            name="virtual_table_record_links_relation_fkey",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_table_id", "source_record_id"],
            [
                "virtual_table_records.organization_id",
                "virtual_table_records.table_id",
                "virtual_table_records.id",
            ],
            name="virtual_table_record_links_source_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "target_table_id", "target_record_id"],
            [
                "virtual_table_records.organization_id",
                "virtual_table_records.table_id",
                "virtual_table_records.id",
            ],
            name="virtual_table_record_links_target_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "source_table_id",
            "column_id",
            "source_record_id",
            "position",
            name="uq_virtual_table_link_position",
        ),
        sa.CheckConstraint("position >= 0 AND position < max_links", name="position"),
    )
    op.create_index(
        "virtual_table_record_links_target_idx",
        "virtual_table_record_links",
        ["organization_id", "target_table_id", "target_record_id", "source_table_id", "column_id"],
    )
    op.create_table(
        "virtual_table_link_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_table_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            name="virtual_table_link_evidence_table_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "source_table_id",
            "source_record_id",
            "column_id",
            "source_revision",
            "position",
            name="uq_virtual_table_link_evidence_position",
        ),
        sa.CheckConstraint("source_revision >= 1", name="source_revision"),
        sa.CheckConstraint("position >= -1", name="position"),
        sa.CheckConstraint(
            "reason IN ('invalid_cell', 'invalid_id', 'missing_target', 'duplicate_target', 'limit_exceeded')",
            name="reason",
        ),
    )
    _backfill(op.get_bind())


def _uuid(value: Any) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _split_cell(
    value: Any, targets: set[UUID], max_links: int
) -> tuple[list[tuple[int, UUID]], list[tuple[int, str, Any]]]:
    # Frozen migration implementation: do not import changing application code.
    if value is None:
        return [], []
    if not isinstance(value, list):
        return [], [(-1, "invalid_cell", value)]
    if len(value) > max_links:
        return [], [(-1, "limit_exceeded", value)]
    links, evidence = [], []
    seen = set()
    for position, item in enumerate(value):
        target_id = _uuid(item)
        if target_id is None:
            evidence.append((position, "invalid_id", item))
        elif target_id in seen:
            evidence.append((position, "duplicate_target", item))
        elif target_id not in targets:
            evidence.append((position, "missing_target", item))
            seen.add(target_id)
        else:
            links.append((len(links), target_id))
            seen.add(target_id)
    return links, evidence


def _backfill(connection: sa.Connection) -> None:
    # This protects the snapshot, not a rolling deployment with old writers.
    connection.execute(
        sa.text(
            "LOCK TABLE virtual_tables, virtual_table_schema_versions, virtual_table_records "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    metadata = sa.MetaData()
    relations = sa.Table("virtual_table_relations", metadata, autoload_with=connection)
    edges = sa.Table("virtual_table_record_links", metadata, autoload_with=connection)
    evidence = sa.Table("virtual_table_link_evidence", metadata, autoload_with=connection)
    records = sa.Table("virtual_table_records", metadata, autoload_with=connection)
    table_orgs = dict(
        connection.execute(sa.text("SELECT id, organization_id FROM virtual_tables")).all()
    )
    schemas = connection.execute(
        sa.text(
            "SELECT t.id, t.organization_id, s.columns "
            "FROM virtual_tables AS t "
            "JOIN virtual_table_schema_versions AS s "
            "ON s.table_id = t.id AND s.version = t.schema_version "
            "ORDER BY t.id"
        )
    ).mappings()
    for schema in schemas:
        definitions: list[_Definition] = []
        for column in schema["columns"]:
            if column.get("type") != "link":
                continue
            column_id = _uuid(column.get("id"))
            target_table_id = _uuid(column.get("link_table_id"))
            max_links = column.get("link_limit")
            if max_links is None:
                max_links = 100
            if (
                column_id is None
                or target_table_id is None
                or table_orgs.get(target_table_id) != schema["organization_id"]
                or type(max_links) is not int
                or not 1 <= max_links <= 100
            ):
                raise RuntimeError(
                    f"Invalid relationship definition in table {schema['id']}; "
                    "repair the schema before retrying this migration"
                )
            definition: _Definition = {
                "organization_id": schema["organization_id"],
                "source_table_id": schema["id"],
                "column_id": column_id,
                "target_table_id": target_table_id,
                "archived": bool(column.get("archived", False)),
                "max_links": max_links,
            }
            definitions.append(definition)
        if not definitions:
            continue
        connection.execute(sa.insert(relations), definitions)
        after = None
        while True:
            query = (
                sa.select(records)
                .where(
                    records.c.organization_id == schema["organization_id"],
                    records.c.table_id == schema["id"],
                )
                .order_by(records.c.id)
                .limit(500)
            )
            if after is not None:
                query = query.where(records.c.id > after)
            batch = connection.execute(query).mappings().all()
            if not batch:
                break
            for definition in definitions:
                column_key = str(definition["column_id"])
                candidates = {
                    target_id
                    for record in batch
                    if isinstance(record["values"].get(column_key), list)
                    and len(record["values"][column_key]) <= definition["max_links"]
                    for item in record["values"][column_key]
                    if (target_id := _uuid(item)) is not None
                }
                target_candidates = list(candidates)
                targets = set()
                for start in range(0, len(target_candidates), 1_000):
                    targets.update(
                        connection.scalars(
                            sa.select(records.c.id).where(
                                records.c.organization_id == schema["organization_id"],
                                records.c.table_id == definition["target_table_id"],
                                records.c.id.in_(target_candidates[start : start + 1_000]),
                            )
                        )
                    )
                new_edges, new_evidence = [], []
                for record in batch:
                    links, held = _split_cell(
                        record["values"].get(column_key), targets, definition["max_links"]
                    )
                    source = {
                        "organization_id": schema["organization_id"],
                        "source_table_id": schema["id"],
                        "source_record_id": record["id"],
                        "column_id": definition["column_id"],
                    }
                    new_edges.extend(
                        {
                            **source,
                            "target_table_id": definition["target_table_id"],
                            "target_record_id": target_id,
                            "position": position,
                            "max_links": definition["max_links"],
                        }
                        for position, target_id in links
                    )
                    new_evidence.extend(
                        {
                            **source,
                            "id": uuid4(),
                            "source_revision": record["revision"],
                            "position": position,
                            "reason": reason,
                            "value": value,
                        }
                        for position, reason, value in held
                    )
                if new_edges:
                    connection.execute(sa.insert(edges), new_edges)
                if new_evidence:
                    connection.execute(sa.insert(evidence), new_evidence)
            after = batch[-1]["id"]


def downgrade() -> None:
    # Original record values and immutable history were never rewritten.
    op.drop_table("virtual_table_link_evidence")
    op.drop_index("virtual_table_record_links_target_idx", table_name="virtual_table_record_links")
    op.drop_table("virtual_table_record_links")
    op.drop_index("virtual_table_relations_target_idx", table_name="virtual_table_relations")
    op.drop_table("virtual_table_relations")
    op.drop_constraint(
        "uq_virtual_table_record_org_table_id", "virtual_table_records", type_="unique"
    )
