"""Formula columns against a real database: worked out on read, kept in step with renames."""

from __future__ import annotations

import uuid

import pytest

from app.schemas.virtual_table import (
    ColumnInput,
    OptionInput,
    RecordCreate,
    RecordExportQuery,
    SchemaUpdate,
    TableCreate,
    TableRead,
)
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables.exceptions import InvalidRecordError, InvalidSchemaError
from tests.integration.virtual_table_support import cid, column, ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


def _kept(table: TableRead) -> list[ColumnInput]:
    """Every column of `table` as a schema change resubmits it."""
    return [
        ColumnInput.model_validate(c.model_dump(exclude={"options"}) | {"options": c.options})
        for c in table.columns
    ]


async def _with(service, ctx, table: TableRead, *added: ColumnInput) -> TableRead:
    return await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(expected_version=table.schema_version, columns=[*_kept(table), *added]),
    )


async def _lines(service, ctx, table: TableRead) -> list[str]:
    export = await service.export_records(ctx, table.id, RecordExportQuery())
    return [line async for line in export.lines]


async def _setup(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    service = VirtualTableService(db)
    ctx = ctx_for(owner, org)
    table = await service.create_table(
        ctx,
        TableCreate(
            name=f"Deals {uuid.uuid4().hex[:6]}",
            columns=[
                column("Name", "text"),
                column("Price", "number"),
                column("Quantity", "integer"),
                column(
                    "Stage",
                    "single_select",
                    options=[OptionInput(label="Open"), OptionInput(label="Won")],
                ),
            ],
        ),
    )
    return service, ctx, table


async def test_a_formula_is_worked_out_for_every_record_read_and_written(db):
    service, ctx, table = await _setup(db)
    table = await _with(
        service,
        ctx,
        table,
        column("Total", "formula", formula="{Price} * {Quantity}"),
        column("Label", "formula", formula='IF({Stage} = "Won", UPPER({Name}), {Name})'),
    )
    won = next(o.id for o in table.columns[3].options if o.label == "Won")
    written = await service.create_record(
        ctx,
        table.id,
        RecordCreate(
            values={
                cid(table, "Name"): "Acme",
                cid(table, "Price"): 2.5,
                cid(table, "Quantity"): 4,
                cid(table, "Stage"): str(won),
            }
        ),
    )
    await service.create_record(ctx, table.id, RecordCreate(values={cid(table, "Name"): "Bare"}))

    page = await service.list_records(ctx, table.id)
    read = await service.get_record(ctx, table.id, written.record.id)

    for record in (written.record, read):
        assert record.values[cid(table, "Total")] == 10
        assert record.values[cid(table, "Label")] == "ACME"
    bare = next(r for r in page.items if r.values[cid(table, "Name")] == "Bare")
    assert cid(table, "Total") not in bare.values
    assert bare.values[cid(table, "Label")] == "Bare"
    assert (await _lines(service, ctx, table))[1:] == [
        "Acme,2.5,4,Won,10,ACME\r\n",
        "Bare,,,,,Bare\r\n",
    ]

    with pytest.raises(InvalidRecordError, match="worked out"):
        await service.create_record(ctx, table.id, RecordCreate(values={cid(table, "Total"): 1}))


async def test_renaming_a_column_rewrites_the_formulas_that_read_it(db):
    service, ctx, table = await _setup(db)
    table = await _with(
        service, ctx, table, column("Total", "formula", formula="{Price} * {Quantity}")
    )
    columns = _kept(table)
    columns[1] = columns[1].model_copy(update={"label": "Unit price"})

    renamed = await service.update_schema(
        ctx, table.id, SchemaUpdate(expected_version=table.schema_version, columns=columns)
    )

    total = next(c for c in renamed.columns if c.label == "Total")
    assert total.formula == "{Unit price} * {Quantity}"


async def test_a_column_a_formula_reads_cannot_be_archived(db):
    service, ctx, table = await _setup(db)
    table = await _with(
        service, ctx, table, column("Total", "formula", formula="{Price} * {Quantity}")
    )

    with pytest.raises(InvalidSchemaError, match="not a live column") as refused:
        await service.update_schema(
            ctx,
            table.id,
            SchemaUpdate(
                expected_version=table.schema_version,
                columns=[c for c in _kept(table) if c.label != "Price"],
            ),
        )
    assert refused.value.details["fields"][0]["field"] == "columns.3.formula"


async def test_a_formula_reads_what_a_rollup_worked_out(db):
    service, ctx, products = await _setup(db)
    item = await service.create_record(
        ctx, products.id, RecordCreate(values={cid(products, "Price"): 30})
    )
    orders = await service.create_table(
        ctx,
        TableCreate(name="Orders", columns=[column("Items", "link", link_table_id=products.id)]),
    )
    orders = await _with(
        service,
        ctx,
        orders,
        column(
            "Net",
            "rollup",
            link_column_id=orders.columns[0].id,
            target_column_id=uuid.UUID(cid(products, "Price")),
            aggregate="sum",
        ),
    )
    orders = await _with(service, ctx, orders, column("Gross", "formula", formula="{Net} * 1.23"))

    written = await service.create_record(
        ctx, orders.id, RecordCreate(values={cid(orders, "Items"): [str(item.record.id)]})
    )

    assert written.record.values[cid(orders, "Gross")] == 36.9


@pytest.mark.parametrize(
    ("formula", "says"),
    [
        ("{Nope} + 1", "not a live column"),
        ("{Price} ** 2", "calculates with"),
        ("", "needs a formula"),
    ],
)
async def test_a_formula_that_cannot_be_one_is_refused_on_the_column(db, formula, says):
    service, ctx, table = await _setup(db)

    with pytest.raises(InvalidSchemaError, match=says) as refused:
        await _with(service, ctx, table, column("Bad", "formula", formula=formula))
    assert refused.value.details["fields"][0]["field"] == "columns.4.formula"
