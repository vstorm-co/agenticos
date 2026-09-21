"""What the Virtual Tables schema guarantees that only a database can.

The service refuses these cases first, but the service is not the last line: a
worker, a script or a second code path writes through the same tables, and a
duplicate external id or a skipped revision must be impossible there too.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.models.virtual_table import (
    VirtualTable,
    VirtualTableOutbox,
    VirtualTableReceipt,
    VirtualTableRecord,
    VirtualTableRecordHistory,
    VirtualTableSchemaVersion,
)
from tests.integration.virtual_table_support import make_org, make_table, make_user

pytestmark = pytest.mark.anyio


def _record(table: VirtualTable, **fields) -> VirtualTableRecord:
    return VirtualTableRecord(
        organization_id=table.organization_id,
        table_id=table.id,
        schema_version=1,
        values={},
        **fields,
    )


async def test_a_live_table_name_is_unique_per_organization(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    other_org = await make_org(db, owner=owner)
    await make_table(db, org=org, owner=owner, name="orders")

    await make_table(db, org=other_org, owner=owner, name="orders")
    with pytest.raises(IntegrityError):
        await make_table(db, org=org, owner=owner, name="orders")


async def test_an_archived_tables_name_can_be_reused(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    first = await make_table(db, org=org, owner=owner, name="orders")
    first.archived_at = datetime.now(UTC)
    await db.flush()

    await make_table(db, org=org, owner=owner, name="orders")


async def test_an_external_id_is_unique_per_table_and_null_ones_never_collide(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    table = await make_table(db, org=org, owner=owner, name="orders")
    other = await make_table(db, org=org, owner=owner, name="invoices")

    db.add_all([_record(table, external_id=None), _record(table, external_id=None)])
    db.add(_record(table, external_id="A-1"))
    db.add(_record(other, external_id="A-1"))
    await db.flush()

    db.add(_record(table, external_id="A-1"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_a_revision_below_one_is_refused(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    table = await make_table(db, org=org, owner=owner, name="orders")

    db.add(_record(table, revision=0))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_a_schema_version_number_is_unique_per_table(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    table = await make_table(db, org=org, owner=owner, name="orders")

    db.add(VirtualTableSchemaVersion(table_id=table.id, version=1, columns=[]))
    await db.flush()
    db.add(VirtualTableSchemaVersion(table_id=table.id, version=1, columns=[]))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_a_receipt_key_is_unique_per_principal_and_operation(db):
    owner = await make_user(db)
    colleague = await make_user(db)
    org = await make_org(db, owner=owner)

    def receipt(principal, operation="record.create"):
        return VirtualTableReceipt(
            organization_id=org.id,
            principal_id=principal.id,
            operation=operation,
            operation_key="k-1",
            payload_hash="h",
        )

    db.add_all([receipt(owner), receipt(colleague), receipt(owner, "record.upsert")])
    await db.flush()

    db.add(receipt(owner))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_an_unknown_receipt_operation_is_refused(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)

    db.add(
        VirtualTableReceipt(
            organization_id=org.id,
            principal_id=owner.id,
            operation="record.explode",
            operation_key="k",
            payload_hash="h",
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_an_unknown_outbox_event_is_refused(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    table = await make_table(db, org=org, owner=owner, name="orders")
    db.add(
        VirtualTableOutbox(
            organization_id=org.id,
            table_id=table.id,
            record_id=uuid.uuid4(),
            event_type="table.record.exploded",
            payload={},
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_deleting_a_record_leaves_its_history(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    table = await make_table(db, org=org, owner=owner, name="orders")
    record = _record(table, external_id="A-1")
    db.add(record)
    await db.flush()
    db.add(
        VirtualTableRecordHistory(
            organization_id=org.id,
            table_id=table.id,
            record_id=record.id,
            revision=1,
            operation="create",
            after={},
        )
    )
    await db.flush()

    await db.execute(delete(VirtualTableRecord).where(VirtualTableRecord.id == record.id))

    kept = await db.scalars(
        select(VirtualTableRecordHistory).where(VirtualTableRecordHistory.record_id == record.id)
    )
    assert len(list(kept)) == 1


async def test_deleting_the_organization_takes_its_tables_with_it(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    table = await make_table(db, org=org, owner=owner, name="orders")
    db.add(_record(table))
    await db.flush()

    await db.execute(delete(type(org)).where(type(org).id == org.id))

    assert await db.scalar(select(VirtualTable).where(VirtualTable.id == table.id)) is None
    assert await db.scalar(select(VirtualTableRecord)) is None


@pytest.mark.security
async def test_a_child_row_cannot_name_a_table_from_another_organization(db):
    """The composite foreign key, not a WHERE clause, keeps a row in its table's tenant."""
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    other_org = await make_org(db, owner=owner)
    table = await make_table(db, org=org, owner=owner, name="orders")

    children = [
        VirtualTableRecord(
            organization_id=other_org.id,
            table_id=table.id,
            schema_version=1,
            values={},
        ),
        VirtualTableRecordHistory(
            organization_id=other_org.id,
            table_id=table.id,
            record_id=uuid.uuid4(),
            revision=1,
            operation="create",
        ),
        VirtualTableOutbox(
            organization_id=other_org.id,
            table_id=table.id,
            record_id=uuid.uuid4(),
            event_type="table.record.created",
            payload={},
        ),
    ]
    for child in children:
        async with db.begin_nested():
            db.add(child)
            with pytest.raises(IntegrityError):
                await db.flush()


async def test_a_child_row_in_its_tables_own_organization_is_accepted(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    table = await make_table(db, org=org, owner=owner, name="orders")

    db.add(_record(table))
    await db.flush()
