"""Records in and out in bulk, against a real database: a batch create and a CSV export."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.exceptions import ExportTooLargeError, NotFoundError
from app.db.models.virtual_table import VirtualTableOutbox
from app.schemas.virtual_table import (
    OptionInput,
    RecordBatchCreate,
    RecordCreate,
    RecordExportQuery,
    RecordFilter,
    RecordSort,
    SchemaUpdate,
    TableUpdate,
)
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables import records as records_module
from app.services.virtual_tables.exceptions import InvalidQueryError, TableArchivedError
from tests.integration.virtual_table_support import (
    cid,
    column,
    ctx_for,
    make_org,
    make_user,
    orders_table,
)

pytestmark = pytest.mark.anyio


async def _setup(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    service = VirtualTableService(db)
    ctx = ctx_for(owner, org)
    return service, ctx, await orders_table(service, ctx)


async def _csv(service, ctx, table, **query) -> str:
    export = await service.export_records(ctx, table.id, RecordExportQuery(**query))
    return "".join([line async for line in export.lines])


async def test_a_batch_writes_every_record_that_fits_and_names_each_that_does_not(db):
    service, ctx, table = await _setup(db)
    customer, quantity = cid(table, "Customer"), cid(table, "Quantity")
    await service.create_record(
        ctx, table.id, RecordCreate(external_id="taken", values={customer: "Old"})
    )

    result = await service.create_records(
        ctx,
        table.id,
        RecordBatchCreate(
            records=[
                RecordCreate(values={customer: "Acme", quantity: 3}),
                RecordCreate(values={quantity: "three"}),
                RecordCreate(external_id="taken", values={customer: "Again"}),
                RecordCreate(external_id="new", values={customer: "Globex"}),
                RecordCreate(external_id="new", values={customer: "Globex twice"}),
            ]
        ),
    )

    assert result.created == 2
    assert [(failure.index, failure.code) for failure in result.failed] == [
        (1, "INVALID_RECORD"),
        (2, "ALREADY_EXISTS"),
        (4, "ALREADY_EXISTS"),
    ]
    events = await db.scalar(
        select(func.count())
        .select_from(VirtualTableOutbox)
        .where(VirtualTableOutbox.table_id == table.id)
    )
    assert events == 3  # the first record, then the batch's two


async def test_a_batch_refuses_a_value_for_an_archived_column_on_its_own(db):
    service, ctx, table = await _setup(db)
    customer, quantity = cid(table, "Customer"), cid(table, "Quantity")
    keep = [
        column(
            c.label,
            c.type,
            id=c.id,
            options=[OptionInput(id=o.id, label=o.label) for o in c.options],
        )
        for c in table.columns
        if c.label != "Quantity"
    ]
    await service.update_schema(ctx, table.id, SchemaUpdate(expected_version=1, columns=keep))

    result = await service.create_records(
        ctx,
        table.id,
        RecordBatchCreate(
            records=[RecordCreate(values={quantity: 1}), RecordCreate(values={customer: "Fits"})]
        ),
    )

    assert result.created == 1
    assert [(failure.index, failure.code) for failure in result.failed] == [(0, "ARCHIVED_COLUMN")]


@pytest.mark.security
async def test_a_batch_into_another_tenants_table_or_an_archived_one_is_refused(db):
    service, ctx, table = await _setup(db)
    other_owner = await make_user(db)
    other = ctx_for(other_owner, await make_org(db, owner=other_owner))
    batch = RecordBatchCreate(records=[RecordCreate(values={})])

    with pytest.raises(NotFoundError):
        await service.create_records(other, table.id, batch)
    await service.archive_table(ctx, table.id)
    with pytest.raises(TableArchivedError):
        await service.create_records(ctx, table.id, batch)


async def test_an_export_writes_what_a_person_reads_in_the_querys_order(db):
    service, ctx, table = await _setup(db)
    status = next(c for c in table.columns if c.label == "Status")
    tags = next(c for c in table.columns if c.label == "Tags")
    rows = [
        {
            "Customer": "Acme, Ltd",
            "Quantity": 2,
            "Total": 10.5,
            "Paid": True,
            "Status": str(status.options[1].id),
            "Tags": [str(tags.options[0].id), str(tags.options[1].id)],
        },
        {"Customer": "=HYPERLINK(1)", "Quantity": 1, "Paid": False},
    ]
    for cells in rows:
        await service.create_record(
            ctx, table.id, RecordCreate(values={cid(table, k): v for k, v in cells.items()})
        )

    written = await _csv(
        service, ctx, table, sort=RecordSort(by=cid(table, "Quantity"), direction="asc")
    )

    assert written.splitlines() == [
        "﻿Customer,Quantity,Total,Paid,Due,Placed,Status,Tags",
        "'=HYPERLINK(1),1,,false,,,,",
        '"Acme, Ltd",2,10.5,true,,,Shipped,Rush; Gift',
    ]


async def test_an_export_narrows_by_filter_and_search_and_writes_the_chosen_columns(
    db, monkeypatch
):
    service, ctx, table = await _setup(db)
    customer, quantity = cid(table, "Customer"), cid(table, "Quantity")
    for i in range(5):
        await service.create_record(
            ctx,
            table.id,
            RecordCreate(values={customer: "Acme" if i % 2 else "Globex", quantity: i}),
        )
    # Several reads, so the file is written a page after another.
    monkeypatch.setattr(records_module, "EXPORT_BATCH", 2)

    written = await _csv(
        service,
        ctx,
        table,
        search="glob",
        filters=[RecordFilter(column_id=quantity, op="gte", value=1)],
        sort=RecordSort(by=quantity, direction="desc"),
        columns=[quantity, customer],
    )
    everything = await _csv(service, ctx, table, columns=[customer])

    assert written.splitlines() == ["﻿Quantity,Customer", "4,Globex", "2,Globex"]
    assert len(everything.splitlines()) == 6


async def test_an_export_refuses_before_writing_a_line(db, monkeypatch):
    service, ctx, table = await _setup(db)
    customer = cid(table, "Customer")
    for name in ("a", "b"):
        await service.create_record(ctx, table.id, RecordCreate(values={customer: name}))

    with pytest.raises(InvalidQueryError):
        await service.export_records(ctx, table.id, RecordExportQuery(columns=[uuid.uuid4()]))
    with pytest.raises(InvalidQueryError):
        await service.export_records(
            ctx, table.id, RecordExportQuery(sort=RecordSort(by="nowhere"))
        )
    monkeypatch.setattr(records_module, "MAX_COUNT", 1)
    with pytest.raises(ExportTooLargeError):
        await service.export_records(ctx, table.id, RecordExportQuery())


@pytest.mark.parametrize(
    ("name", "filename"),
    [("Zamówienia 2026 / Q3", "Zam-wienia-2026-Q3.csv"), ("Заказы", "table.csv")],
)
async def test_an_export_is_named_after_its_table_in_characters_a_file_name_keeps(
    db, name, filename
):
    service, ctx, table = await _setup(db)
    await service.update_table(ctx, table.id, TableUpdate(name=name))

    export = await service.export_records(ctx, table.id, RecordExportQuery())

    assert export.filename == filename


async def test_a_batch_record_whose_external_id_is_taken_in_a_race_is_reported_as_taken(
    db, monkeypatch
):
    """The lookup found nothing, and a concurrent create took the id before the insert."""
    service, ctx, table = await _setup(db)
    await service.create_record(ctx, table.id, RecordCreate(external_id="raced", values={}))

    async def nothing_yet(*_args):
        return None

    monkeypatch.setattr(service, "_lookup", nothing_yet)
    result = await service.create_records(
        ctx, table.id, RecordBatchCreate(records=[RecordCreate(external_id="raced", values={})])
    )

    assert (result.created, [failure.code for failure in result.failed]) == (0, ["ALREADY_EXISTS"])
