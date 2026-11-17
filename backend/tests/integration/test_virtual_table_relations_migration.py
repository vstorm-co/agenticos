"""The relationship migration preserves raw evidence and upgrades real PostgreSQL DDL.

The integration fixture owns a disposable, process-specific database. Downgrading
and upgrading only this revision inside its transaction rehearses the actual DDL
and backfill without applying any migration to a developer or deployed database.
"""

import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import insert, inspect, select, text

from app.db.base import Base
from app.db.models.virtual_table import VirtualTableRecord, VirtualTableSchemaVersion
from app.db.models.virtual_table_relation import (
    VirtualTableLinkEvidence,
    VirtualTableRecordLink,
    VirtualTableRelation,
)
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import RecordCreate, SchemaUpdate, TableCreate
from app.services.virtual_tables import VirtualTableService
from tests.integration.test_virtual_table_relations import _columns, _setup
from tests.integration.virtual_table_support import cid, column, ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio

_PATH = Path(__file__).parents[2] / "alembic" / "versions" / "0327_virtual_table_relations.py"
_SPEC = importlib.util.spec_from_file_location("relations_migration", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)


def _migrate(connection, direction):
    with Operations.context(
        MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    ):
        getattr(_MIGRATION, direction)()


async def test_backfill_keeps_ids_revisions_order_archived_fields_and_every_rejected_value(db):
    service, ctx, org, _owner, source, target, targets = await _setup(db)
    key = cid(source, "Customers")
    archived = await service.update_schema(
        ctx,
        source.id,
        SchemaUpdate(
            expected_version=source.schema_version,
            columns=_columns(source, archived=True),
        ),
    )
    other_owner = await make_user(db)
    other_org = await make_org(db, owner=other_owner)
    foreign_ctx = ctx_for(other_owner, other_org)
    foreign_table = await VirtualTableService(db).create_table(
        foreign_ctx, TableCreate(name="Foreign", columns=[column("Name", "text")])
    )
    foreign_row = await service.create_record(
        foreign_ctx, foreign_table.id, RecordCreate(values={cid(foreign_table, "Name"): "Private"})
    )
    missing = str(uuid4())
    cases = [
        [str(targets[2]), str(targets[0])],
        [str(targets[0]), str(targets[0]), missing, "bad", 3],
        {"unresolved": "retain this whole object"},
        [str(foreign_row.record.id)],
        [str(targets[1])] * 101,
        None,
        [],
    ]
    ids = [uuid4() for _ in range(508)]  # exercise the second 500-row keyset page
    originals = {
        record_id: {key: cases[index] if index < len(cases) else []}
        for index, record_id in enumerate(ids)
    }
    await db.execute(
        insert(VirtualTableRecord),
        [
            {
                "id": record_id,
                "organization_id": org.id,
                "table_id": source.id,
                "schema_version": source.schema_version,
                "revision": 7,
                "values": value,
            }
            for record_id, value in originals.items()
        ],
    )
    connection = await db.connection()
    await connection.run_sync(lambda conn: _migrate(conn, "downgrade"))
    await connection.run_sync(lambda conn: _migrate(conn, "upgrade"))

    relation = await db.scalar(
        select(VirtualTableRelation)
        .where(VirtualTableRelation.source_table_id == source.id)
        .execution_options(populate_existing=True)
    )
    assert relation.column_id == UUID(key)
    assert relation.target_table_id == target.id
    assert relation.archived
    assert relation.max_links == 100
    edges = list(
        await db.scalars(
            select(VirtualTableRecordLink)
            .where(VirtualTableRecordLink.source_record_id == ids[0])
            .order_by(VirtualTableRecordLink.position)
        )
    )
    assert [(edge.position, edge.target_record_id) for edge in edges] == [
        (0, targets[2]),
        (1, targets[0]),
    ]

    held = list(
        await db.scalars(
            select(VirtualTableLinkEvidence).where(
                VirtualTableLinkEvidence.source_table_id == source.id
            )
        )
    )
    by_source = {}
    for item in held:
        by_source.setdefault(item.source_record_id, []).append(item)
    assert {item.reason for item in by_source[ids[1]]} == {
        "duplicate_target",
        "missing_target",
        "invalid_id",
    }
    assert [(item.reason, item.value) for item in by_source[ids[2]]] == [("invalid_cell", cases[2])]
    assert [(item.reason, item.value) for item in by_source[ids[3]]] == [
        ("missing_target", cases[3][0])
    ]
    assert [(item.reason, item.value) for item in by_source[ids[4]]] == [
        ("limit_exceeded", cases[4])
    ]
    assert all(item.source_revision == 7 for item in held)
    rows = list(
        await db.scalars(
            select(VirtualTableRecord)
            .where(VirtualTableRecord.table_id == source.id)
            .execution_options(populate_existing=True)
        )
    )
    assert {row.id: row.values for row in rows} == originals
    assert all(row.revision == 7 and row.schema_version == source.schema_version for row in rows)

    # Archive/restore keeps the same field identity; canonical projection runs
    # before public-cell validation even for an object or a mixed malformed list.
    await service.update_schema(
        ctx,
        source.id,
        SchemaUpdate(
            expected_version=archived.schema_version,
            columns=_columns(archived, archived=False),
        ),
    )
    malformed = await service.get_record(ctx, source.id, ids[2])
    mixed = await service.get_record(ctx, source.id, ids[1])
    assert malformed.values[key] == []
    assert mixed.values[key] == [str(targets[0])]

    # Rolling this schema back leaves the original live JSON available to the
    # previous application. It does not attempt to reconstruct deleted history.
    await connection.run_sync(lambda conn: _migrate(conn, "downgrade"))
    stored = await virtual_table_repo.get_record(
        db, ids[2], table_id=source.id, organization_id=org.id
    )
    assert stored.values == originals[ids[2]]
    assert stored.revision == 7


@pytest.mark.security
@pytest.mark.parametrize(
    "defect", ["cross_organization", "zero_limit", "false_limit", "empty_limit"]
)
async def test_invalid_definition_aborts_cutover_without_rewriting_rows(db, defect):
    _service, _ctx, org, _owner, source, _target, _targets = await _setup(db)
    foreign_owner = await make_user(db)
    foreign_org = await make_org(db, owner=foreign_owner)
    foreign_table = await _service.create_table(
        ctx_for(foreign_owner, foreign_org),
        TableCreate(name="Foreign definition", columns=[column("Name", "text")]),
    )
    schema = await db.scalar(
        select(VirtualTableSchemaVersion).where(
            VirtualTableSchemaVersion.table_id == source.id,
            VirtualTableSchemaVersion.version == source.schema_version,
        )
    )
    invalid = {
        "cross_organization": {"link_table_id": str(foreign_table.id)},
        "zero_limit": {"link_limit": 0},
        "false_limit": {"link_limit": False},
        "empty_limit": {"link_limit": ""},
    }[defect]
    schema.columns = [
        {**item, **invalid} if item["type"] == "link" else item for item in schema.columns
    ]
    await db.flush()
    original = list(schema.columns)
    connection = await db.connection()
    await connection.run_sync(lambda conn: _migrate(conn, "downgrade"))
    with pytest.raises(RuntimeError, match="Invalid relationship definition"):
        async with db.begin_nested():
            # Enlist the connection in the session's lazy SAVEPOINT before DDL.
            nested_connection = await db.connection()
            await nested_connection.run_sync(lambda conn: _migrate(conn, "upgrade"))
    await db.refresh(schema)
    assert schema.columns == original
    assert await virtual_table_repo.get_table(db, source.id, organization_id=org.id) is not None
    remaining_tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
    assert {
        "virtual_table_relations",
        "virtual_table_record_links",
        "virtual_table_link_evidence",
    }.isdisjoint(remaining_tables)
    constraint_exists = await db.scalar(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'uq_virtual_table_record_org_table_id' "
            "AND conrelid = 'virtual_table_records'::regclass)"
        )
    )
    assert not constraint_exists
