"""The models name themselves in logs without dumping cell values."""

import uuid

from app.db.models.virtual_table import (
    VirtualTable,
    VirtualTableOutbox,
    VirtualTableReceipt,
    VirtualTableRecord,
    VirtualTableRecordHistory,
    VirtualTableSchemaVersion,
)


def test_a_repr_identifies_the_row_but_never_prints_its_values():
    table_id = uuid.uuid4()
    reprs = [
        repr(VirtualTable(organization_id=uuid.uuid4(), name="orders")),
        repr(VirtualTableSchemaVersion(table_id=table_id, version=2, columns=[])),
        repr(VirtualTableRecord(table_id=table_id, revision=3, values={"secret": "s3cret"})),
        repr(
            VirtualTableRecordHistory(
                record_id=uuid.uuid4(), revision=1, operation="create", after={"secret": "s3cret"}
            )
        ),
        repr(VirtualTableReceipt(operation="record.create", operation_key="k", outcome={"a": "b"})),
        repr(VirtualTableOutbox(event_type="table.record.created", record_id=uuid.uuid4())),
    ]
    assert all(reprs)
    assert not any("s3cret" in text for text in reprs)
