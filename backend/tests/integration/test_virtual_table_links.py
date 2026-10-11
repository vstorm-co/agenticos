"""Link, lookup and rollup columns against a real database: what a record reads through its links."""

from __future__ import annotations

import uuid

import pytest

from app.db.models.resource_grant import GrantLevel
from app.repositories import resource_grant_repo
from app.schemas.virtual_table import (
    ColumnInput,
    OptionInput,
    RecordCreate,
    RecordExportQuery,
    RecordFilter,
    RecordQuery,
    RecordUpdate,
    SchemaUpdate,
    TableCreate,
    TableRead,
)
from app.services.access import TABLE
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables.exceptions import (
    InvalidQueryError,
    InvalidRecordError,
    InvalidSchemaError,
)
from tests.integration.virtual_table_support import cid, column, ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


async def _products(service, ctx) -> tuple[TableRead, dict[str, str]]:
    """A products table and the ids of three products in it."""
    table = await service.create_table(
        ctx,
        TableCreate(
            name=f"Products {uuid.uuid4().hex[:6]}",
            visibility="org",
            columns=[
                column("Name", "text"),
                column("Price", "number"),
                column("Shipped", "date"),
                column(
                    "Kind",
                    "single_select",
                    options=[OptionInput(label="Book"), OptionInput(label="Pen")],
                ),
            ],
        ),
    )
    book, pen = (str(option.id) for option in table.columns[3].options)
    ids = {}
    for name, price, shipped, kind in (
        ("Atlas", 30, "2026-01-05", book),
        ("Quill", 5.5, "2026-03-01", pen),
        ("Blank", None, None, None),
    ):
        values = {cid(table, "Name"): name, cid(table, "Kind"): kind}
        if price is not None:
            values[cid(table, "Price")] = price
            values[cid(table, "Shipped")] = shipped
        written = await service.create_record(ctx, table.id, RecordCreate(values=values))
        ids[name] = str(written.record.id)
    return table, ids


async def _orders(service, ctx, products: TableRead, *reading: ColumnInput) -> TableRead:
    """An orders table linking to `products`, then given the columns read through the link."""
    table = await service.create_table(
        ctx,
        TableCreate(
            name=f"Orders {uuid.uuid4().hex[:6]}",
            visibility="org",
            columns=[
                column("Ref", "text"),
                column("Items", "link", link_table_id=products.id),
            ],
        ),
    )
    if not reading:
        return table
    link = uuid.UUID(cid(table, "Items"))
    kept = [
        ColumnInput(
            id=existing.id,
            label=existing.label,
            type=existing.type,
            link_table_id=existing.link_table_id,
        )
        for existing in table.columns
    ]
    return await service.update_schema(
        ctx,
        table.id,
        SchemaUpdate(
            expected_version=table.schema_version,
            columns=[
                *kept,
                *(item.model_copy(update={"link_column_id": link}) for item in reading),
            ],
        ),
    )


async def _setup(db):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    return VirtualTableService(db), ctx_for(owner, org), org


def _reading(products: TableRead) -> list[ColumnInput]:
    price = uuid.UUID(cid(products, "Price"))
    placeholder = uuid.uuid4()  # replaced with the link column's id by `_orders`
    return [
        column(
            "Names",
            "lookup",
            link_column_id=placeholder,
            target_column_id=uuid.UUID(cid(products, "Name")),
        ),
        column(
            "Kinds",
            "lookup",
            link_column_id=placeholder,
            target_column_id=uuid.UUID(cid(products, "Kind")),
        ),
        column("Count", "rollup", link_column_id=placeholder, aggregate="count"),
        column(
            "Sum", "rollup", link_column_id=placeholder, target_column_id=price, aggregate="sum"
        ),
        column(
            "Avg", "rollup", link_column_id=placeholder, target_column_id=price, aggregate="avg"
        ),
        column(
            "Cheapest",
            "rollup",
            link_column_id=placeholder,
            target_column_id=price,
            aggregate="min",
        ),
        column(
            "Last shipped",
            "rollup",
            link_column_id=placeholder,
            target_column_id=uuid.UUID(cid(products, "Shipped")),
            aggregate="max",
        ),
    ]


async def test_a_record_reads_its_links_by_name_and_works_out_what_reads_through_them(db):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products, *_reading(products))

    written = await service.create_record(
        ctx,
        orders.id,
        RecordCreate(
            values={
                cid(orders, "Ref"): "A-1",
                cid(orders, "Items"): [ids["Atlas"], ids["Quill"], ids["Blank"]],
            }
        ),
    )
    read = await service.get_record(ctx, orders.id, written.record.id)

    for record in (written.record, read):
        assert [linked.label for linked in record.links[cid(orders, "Items")]] == [
            "Atlas",
            "Quill",
            "Blank",
        ]
        values = record.values
        assert values[cid(orders, "Names")] == ["Atlas", "Quill", "Blank"]
        assert values[cid(orders, "Kinds")] == ["Book", "Pen"]
        assert values[cid(orders, "Count")] == 3
        assert values[cid(orders, "Sum")] == 35.5
        assert values[cid(orders, "Avg")] == 17.75
        assert values[cid(orders, "Cheapest")] == 5.5
        assert values[cid(orders, "Last shipped")] == "2026-03-01"


async def test_a_page_of_records_is_read_through_its_links_and_an_empty_link_reads_nothing(db):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products, *_reading(products))
    await service.create_record(
        ctx, orders.id, RecordCreate(values={cid(orders, "Items"): [ids["Atlas"]]})
    )
    await service.create_record(ctx, orders.id, RecordCreate(values={cid(orders, "Ref"): "none"}))

    page = await service.list_records(ctx, orders.id)

    linked, unlinked = sorted(page.items, key=lambda record: cid(orders, "Ref") in record.values)
    assert linked.values[cid(orders, "Sum")] == 30
    assert unlinked.values.get(cid(orders, "Names")) is None
    assert unlinked.values[cid(orders, "Count")] == 0
    assert unlinked.values.get(cid(orders, "Sum")) is None


async def test_a_linked_record_deleted_since_is_no_longer_named_or_counted(db):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products, *_reading(products))
    written = await service.create_record(
        ctx, orders.id, RecordCreate(values={cid(orders, "Items"): [ids["Atlas"], ids["Quill"]]})
    )

    await service.delete_record(ctx, products.id, uuid.UUID(ids["Quill"]), expected_revision=1)
    read = await service.get_record(ctx, orders.id, written.record.id)

    assert [linked.label for linked in read.links[cid(orders, "Items")]] == ["Atlas"]
    assert read.values[cid(orders, "Count")] == 1


async def test_a_link_is_filtered_by_the_record_it_names(db):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products)
    await service.create_record(
        ctx,
        orders.id,
        RecordCreate(values={cid(orders, "Ref"): "a", cid(orders, "Items"): [ids["Atlas"]]}),
    )
    await service.create_record(
        ctx,
        orders.id,
        RecordCreate(values={cid(orders, "Ref"): "b", cid(orders, "Items"): [ids["Quill"]]}),
    )

    page = await service.list_records(
        ctx,
        orders.id,
        RecordQuery(
            filters=[
                RecordFilter(
                    column_id=uuid.UUID(cid(orders, "Items")), op="contains", value=ids["Quill"]
                )
            ]
        ),
    )

    assert [record.values[cid(orders, "Ref")] for record in page.items] == ["b"]


async def test_a_worked_out_column_is_neither_filtered_nor_written(db):
    service, ctx, _org = await _setup(db)
    products, _ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products, *_reading(products))

    with pytest.raises(InvalidQueryError):
        await service.list_records(
            ctx,
            orders.id,
            RecordQuery(
                filters=[RecordFilter(column_id=uuid.UUID(cid(orders, "Sum")), op="gt", value=1)]
            ),
        )
    with pytest.raises(InvalidRecordError, match="worked out"):
        await service.create_record(ctx, orders.id, RecordCreate(values={cid(orders, "Sum"): 3}))


async def test_a_link_to_a_record_the_table_does_not_hold_is_refused(db):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products)
    written = await service.create_record(
        ctx, orders.id, RecordCreate(values={cid(orders, "Items"): [ids["Atlas"]]})
    )

    with pytest.raises(InvalidRecordError, match="No record"):
        await service.create_record(
            ctx, orders.id, RecordCreate(values={cid(orders, "Items"): [str(uuid.uuid4())]})
        )
    with pytest.raises(InvalidRecordError, match="No record"):
        await service.update_record(
            ctx,
            orders.id,
            written.record.id,
            RecordUpdate(expected_revision=1, values={cid(orders, "Items"): [str(orders.id)]}),
        )


@pytest.mark.security
async def test_a_reader_who_cannot_see_the_linked_table_gets_no_names_and_no_values_from_it(db):
    service, ctx, org = await _setup(db)
    products, ids = await _products(service, ctx)
    private = await service.create_table(
        ctx, TableCreate(name="Private stock", columns=[column("Name", "text")])
    )
    secret = await service.create_record(
        ctx, private.id, RecordCreate(values={cid(private, "Name"): "Classified"})
    )
    orders = await service.create_table(
        ctx,
        TableCreate(
            name="Mixed",
            visibility="org",
            columns=[column("Items", "link", link_table_id=private.id)],
        ),
    )
    written = await service.create_record(
        ctx, orders.id, RecordCreate(values={cid(orders, "Items"): [str(secret.record.id)]})
    )
    colleague = await make_user(db)
    member = ctx_for(colleague, org, "member")
    # May write the orders, and read the products, but not the private stock.
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=orders.id,
        level=GrantLevel.EDIT,
    )

    read = await service.get_record(member, orders.id, written.record.id)

    assert cid(orders, "Items") not in read.links
    assert "Classified" not in str(read.model_dump())
    with pytest.raises(InvalidRecordError, match="cannot be reached"):
        await service.create_record(
            member, orders.id, RecordCreate(values={cid(orders, "Items"): [ids["Atlas"]]})
        )


async def test_an_export_names_links_and_writes_what_reads_through_them(db):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products, *_reading(products)[:2])
    await service.create_record(
        ctx, orders.id, RecordCreate(values={cid(orders, "Items"): [ids["Atlas"], ids["Quill"]]})
    )

    export = await service.export_records(ctx, orders.id, RecordExportQuery())
    lines = [line async for line in export.lines]

    assert lines[1] == ",Atlas; Quill,Atlas; Quill,Book; Pen\r\n"


class TestSchema:
    async def test_a_link_names_a_table_the_creator_can_see(self, db):
        service, ctx, org = await _setup(db)
        private = await service.create_table(ctx, TableCreate(name="Hidden"))
        colleague = await make_user(db)
        member = ctx_for(colleague, org, "member")

        for link_table_id in (uuid.uuid4(), private.id):
            with pytest.raises(InvalidSchemaError, match="cannot see"):
                await service.create_table(
                    member,
                    TableCreate(
                        name=f"T {uuid.uuid4().hex[:6]}",
                        columns=[column("L", "link", link_table_id=link_table_id)],
                    ),
                )

    async def test_a_link_to_an_archived_table_is_refused(self, db):
        service, ctx, _org = await _setup(db)
        gone = await service.create_table(ctx, TableCreate(name="Gone"))
        await service.archive_table(ctx, gone.id)

        with pytest.raises(InvalidSchemaError, match="archived"):
            await service.create_table(
                ctx, TableCreate(name="T", columns=[column("L", "link", link_table_id=gone.id)])
            )

    async def test_a_link_keeps_its_table(self, db):
        service, ctx, _org = await _setup(db)
        products, _ids = await _products(service, ctx)
        other, _ = await _products(service, ctx)
        orders = await _orders(service, ctx, products)
        items = next(c for c in orders.columns if c.label == "Items")

        with pytest.raises(InvalidSchemaError, match="keeps the table"):
            await service.update_schema(
                ctx,
                orders.id,
                SchemaUpdate(
                    expected_version=orders.schema_version,
                    columns=[column("Items", "link", id=items.id, link_table_id=other.id)],
                ),
            )

    @pytest.mark.parametrize(
        ("label", "aggregate", "target", "says"),
        [
            ("Sum", "sum", "Name", "column of numbers"),
            ("Min", "min", "Kind", "numbers or dates"),
            ("Missing", "max", None, "live column"),
        ],
    )
    async def test_a_rollup_reads_a_column_its_working_out_suits(
        self, db, label, aggregate, target, says
    ):
        service, ctx, _org = await _setup(db)
        products, _ids = await _products(service, ctx)
        target_id = uuid.UUID(cid(products, target)) if target else uuid.uuid4()

        with pytest.raises(InvalidSchemaError, match=says):
            await _orders(
                service,
                ctx,
                products,
                column(
                    label,
                    "rollup",
                    link_column_id=uuid.uuid4(),
                    target_column_id=target_id,
                    aggregate=aggregate,
                ),
            )

    async def test_a_lookup_reads_through_a_saved_link_of_the_same_table(self, db):
        service, ctx, _org = await _setup(db)
        products, _ids = await _products(service, ctx)
        orders = await _orders(service, ctx, products)

        with pytest.raises(InvalidSchemaError, match="not a live link column"):
            await service.update_schema(
                ctx,
                orders.id,
                SchemaUpdate(
                    expected_version=orders.schema_version,
                    columns=[
                        column("Ref", "text", id=orders.columns[0].id),
                        column(
                            "Names",
                            "lookup",
                            link_column_id=orders.columns[0].id,
                            target_column_id=uuid.uuid4(),
                        ),
                    ],
                ),
            )

    async def test_a_lookup_does_not_read_another_link_or_worked_out_column(self, db):
        service, ctx, _org = await _setup(db)
        products, _ids = await _products(service, ctx)
        orders = await _orders(service, ctx, products, *_reading(products)[:1])
        names = next(c for c in orders.columns if c.label == "Names")
        shipments = await service.create_table(
            ctx,
            TableCreate(
                name="Shipments", columns=[column("Orders", "link", link_table_id=orders.id)]
            ),
        )
        link = shipments.columns[0]

        for target in (names.id, next(c.id for c in orders.columns if c.label == "Items")):
            with pytest.raises(InvalidSchemaError, match="not another link"):
                await service.update_schema(
                    ctx,
                    shipments.id,
                    SchemaUpdate(
                        expected_version=shipments.schema_version,
                        columns=[
                            column("Orders", "link", id=link.id, link_table_id=orders.id),
                            column(
                                "Names", "lookup", link_column_id=link.id, target_column_id=target
                            ),
                        ],
                    ),
                )

    async def test_archiving_a_link_column_refuses_while_a_lookup_reads_it(self, db):
        service, ctx, _org = await _setup(db)
        products, _ids = await _products(service, ctx)
        orders = await _orders(service, ctx, products, *_reading(products)[:1])
        ref, _items, names = orders.columns

        with pytest.raises(InvalidSchemaError, match="not a live link column"):
            await service.update_schema(
                ctx,
                orders.id,
                SchemaUpdate(
                    expected_version=orders.schema_version,
                    columns=[
                        column("Ref", "text", id=ref.id),
                        column(
                            "Names",
                            "lookup",
                            id=names.id,
                            link_column_id=names.link_column_id,
                            target_column_id=names.target_column_id,
                        ),
                    ],
                ),
            )


async def test_a_record_with_no_text_is_named_by_its_external_id_and_reads_choices_as_labels(db):
    service, ctx, _org = await _setup(db)
    tags = await service.create_table(
        ctx,
        TableCreate(
            name="Tagged",
            columns=[
                column("Size", "integer"),
                column(
                    "Labels",
                    "multi_select",
                    options=[OptionInput(label="Red"), OptionInput(label="Blue")],
                ),
            ],
        ),
    )
    red, blue = (str(option.id) for option in tags.columns[1].options)
    tagged = await service.create_record(
        ctx,
        tags.id,
        RecordCreate(
            external_id="T-1", values={cid(tags, "Size"): 2, cid(tags, "Labels"): [red, blue]}
        ),
    )
    orders = await _orders(
        service,
        ctx,
        tags,
        column(
            "Colours",
            "lookup",
            link_column_id=uuid.uuid4(),
            target_column_id=uuid.UUID(cid(tags, "Labels")),
        ),
        column(
            "Sizes",
            "lookup",
            link_column_id=uuid.uuid4(),
            target_column_id=uuid.UUID(cid(tags, "Size")),
        ),
    )
    written = await service.create_record(
        ctx, orders.id, RecordCreate(values={cid(orders, "Items"): [str(tagged.record.id)]})
    )

    assert [linked.label for linked in written.record.links[cid(orders, "Items")]] == ["T-1"]
    assert written.record.values[cid(orders, "Colours")] == ["Red", "Blue"]
    assert written.record.values[cid(orders, "Sizes")] == [2]

    # The column a lookup reads, archived since, leaves it reading nothing.
    await service.update_schema(
        ctx,
        tags.id,
        SchemaUpdate(
            expected_version=tags.schema_version,
            columns=[column("Size", "integer", id=tags.columns[0].id)],
        ),
    )
    read = await service.get_record(ctx, orders.id, written.record.id)

    assert cid(orders, "Colours") not in read.values
    assert read.values[cid(orders, "Sizes")] == [2]
