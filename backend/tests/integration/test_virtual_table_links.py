"""Link, lookup and rollup columns against a real database: what a record reads through its links."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, event

from app.db.models.resource_grant import GrantLevel
from app.db.models.virtual_table import VirtualTableRecord
from app.repositories import resource_grant_repo, virtual_table_repo
from app.schemas.table_view import TableViewCreate
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
from app.services.virtual_tables import (
    ReadDeadline,
    TableViewService,
    VirtualTableService,
    computed,
)
from app.services.virtual_tables.exceptions import (
    InvalidQueryError,
    InvalidRecordError,
    InvalidSchemaError,
)
from tests.integration.virtual_table_support import (
    bound_view,
    cid,
    column,
    ctx_for,
    insert_rows,
    make_org,
    make_user,
    shaped_size,
    shaper,
)

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


# -- reading a view for a page -------------------------------------------------


def _deadline() -> ReadDeadline:
    return ReadDeadline(60, 2_000)


async def _read(service, ctx, bound, named, *, max_bytes=4 * 1024 * 1024, deadline=None):
    return await service.read_bound(
        ctx,
        bound,
        column_ids=named,
        shape=shaper(bound.columns, named),
        max_records=1_000,
        max_bytes=max_bytes,
        deadline=deadline or _deadline(),
    )


def _spy(monkeypatch, target, name):
    """Wrap one coroutine function, recording each call's arguments and what it returned."""
    real = getattr(target, name)
    calls: list[tuple[tuple, dict, object]] = []

    async def spy(*args, **kwargs):
        result = await real(*args, **kwargs)
        calls.append((args, kwargs, result))
        return result

    monkeypatch.setattr(target, name, spy)
    return calls


def _on(calls, table_id) -> list:
    return [call for call in calls if call[1].get("table_id") == table_id]


async def _specs(service, ctx, *, visibility="org", count=4, size=900_000):
    """A products table whose records each carry a large spec, and their ids."""
    products = await service.create_table(
        ctx,
        TableCreate(
            name=f"Specs {uuid.uuid4().hex[:6]}",
            visibility=visibility,
            columns=[column("Name", "text"), column("Spec", "long_text")],
        ),
    )
    ids = await insert_rows(
        service.db,
        products,
        [{cid(products, "Name"): f"P{n}", cid(products, "Spec"): "s" * size} for n in range(count)],
    )
    return products, ids


async def _spec_orders(service, ctx, products, product_ids):
    """Orders, each linking to one product and looking up its spec."""
    orders = await _orders(
        service,
        ctx,
        products,
        column(
            "Specs",
            "lookup",
            link_column_id=uuid.uuid4(),
            target_column_id=uuid.UUID(cid(products, "Spec")),
        ),
    )
    await insert_rows(
        service.db,
        orders,
        [
            {cid(orders, "Ref"): f"O{n}", cid(orders, "Items"): [str(product_id)]}
            for n, product_id in enumerate(product_ids)
        ],
    )
    return orders


async def test_read_bound_never_loads_linked_cells_past_the_budget(db, monkeypatch):
    service, ctx, _org = await _setup(db)
    products, ids = await _specs(service, ctx)
    orders = await _spec_orders(service, ctx, products, ids)
    bound = await bound_view(db, ctx, orders.id)
    named = [uuid.UUID(cid(orders, "Ref")), uuid.UUID(cid(orders, "Specs"))]
    calls = _spy(monkeypatch, virtual_table_repo, "get_record_cells_by_ids")
    max_bytes = 2_000_000

    read = await _read(service, ctx, bound, named, max_bytes=max_bytes)

    loaded = [cell for _args, _kwargs, cells in _on(calls, products.id) for cell in cells]
    assert read.stopped_by == "bytes"
    assert [record["Ref"] for record in read.records] == ["O0", "O1"]
    assert sum(shaped_size(cell.values) for cell in loaded) <= max_bytes
    assert read.bytes <= max_bytes


@pytest.mark.security
async def test_linked_rows_the_viewer_cannot_see_never_count_against_the_budget(db, monkeypatch):
    service, ctx, org = await _setup(db)
    products, ids = await _specs(service, ctx, visibility="private")
    orders = await _spec_orders(service, ctx, products, ids)
    bound = await bound_view(db, ctx, orders.id, visibility="shared")
    colleague = await make_user(db)
    member = ctx_for(colleague, org, "member")
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=orders.id,
        level=GrantLevel.READ,
    )
    named = [
        uuid.UUID(cid(orders, "Ref")),
        uuid.UUID(cid(orders, "Items")),
        uuid.UUID(cid(orders, "Specs")),
    ]
    cells = _spy(monkeypatch, virtual_table_repo, "get_record_cells_by_ids")
    sizes = _spy(monkeypatch, virtual_table_repo, "get_record_sizes_by_ids")

    read = await _read(service, member, bound, named, max_bytes=10_000)

    assert read.stopped_by is None
    assert [record["Ref"] for record in read.records] == ["O0", "O1", "O2", "O3"]
    assert all(record["Items"] == [] for record in read.records)
    assert not _on(cells, products.id) and not _on(sizes, products.id)
    await db.execute(delete(VirtualTableRecord).where(VirtualTableRecord.table_id == products.id))
    emptied = await _read(service, ctx, bound, named, max_bytes=10_000)
    assert read.records == emptied.records


async def test_a_linked_table_is_checked_once_per_binding(db, monkeypatch):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products, *_reading(products)[:2])
    await insert_rows(
        db, orders, [{cid(orders, "Items"): [ids["Atlas"], ids["Quill"]]} for _ in range(250)]
    )
    bound = await bound_view(db, ctx, orders.id)
    tables = _spy(monkeypatch, virtual_table_repo, "get_table")
    access = _spy(monkeypatch, computed, "resolve_access")

    read = await _read(
        service, ctx, bound, [uuid.UUID(cid(orders, "Names")), uuid.UUID(cid(orders, "Kinds"))]
    )

    assert len(read.records) == 250
    assert read.records[0]["Names"] == ["Atlas", "Quill"]
    assert read.records[-1]["Kinds"] == ["Book", "Pen"]
    assert [args[1] for args, _kwargs, _found in tables] == [products.id]
    assert [args[2].id for args, _kwargs, _allowed in access] == [products.id]


async def test_read_bound_reads_only_the_named_links(db, monkeypatch):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    other, _other_ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products)
    orders = await service.update_schema(
        ctx,
        orders.id,
        SchemaUpdate(
            expected_version=orders.schema_version,
            columns=[
                *(
                    ColumnInput(
                        id=item.id,
                        label=item.label,
                        type=item.type,
                        link_table_id=item.link_table_id,
                    )
                    for item in orders.columns
                ),
                column("Other", "link", link_table_id=other.id),
            ],
        ),
    )
    await insert_rows(
        db,
        orders,
        [{cid(orders, "Items"): [ids["Atlas"]], cid(orders, "Other"): [_other_ids["Quill"]]}],
    )
    bound = await bound_view(db, ctx, orders.id)
    linked = _spy(monkeypatch, computed, "_linked_table")

    read = await _read(service, ctx, bound, [uuid.UUID(cid(orders, "Items"))])

    assert read.records[0]["Items"] == [{"id": ids["Atlas"], "label": "Atlas"}]
    assert [args[2] for args, _kwargs, _found in linked] == [products.id]


async def test_read_bound_reads_only_the_targets_and_name_of_linked_rows(db, monkeypatch):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products, *_reading(products)[3:4])
    await insert_rows(db, orders, [{cid(orders, "Items"): [ids["Atlas"], ids["Quill"]]}])
    tags = await service.create_table(
        ctx, TableCreate(name="Tagged", columns=[column("Size", "integer")])
    )
    tag_ids = await insert_rows(
        db, tags, [{cid(tags, "Size"): 1}, {cid(tags, "Size"): 2}], external_ids=["T-1", None]
    )
    tagged = await _orders(service, ctx, tags)
    await insert_rows(db, tagged, [{cid(tagged, "Items"): [str(i) for i in tag_ids]}])
    calls = _spy(monkeypatch, virtual_table_repo, "get_record_cells_by_ids")

    read = await _read(
        service, ctx, await bound_view(db, ctx, orders.id), [uuid.UUID(cid(orders, "Sum"))]
    )
    labelled = await _read(
        service, ctx, await bound_view(db, ctx, tagged.id), [uuid.UUID(cid(tagged, "Items"))]
    )

    assert read.records[0]["Sum"] == 35.5
    assert {
        key
        for _args, _kwargs, cells in _on(calls, products.id)
        for cell in cells
        for key in cell.values
    } == {cid(products, "Price"), cid(products, "Name")}
    assert [linked["label"] for linked in labelled.records[0]["Items"]] == [
        "T-1",
        str(tag_ids[1])[:8],
    ]
    assert not [cell for _a, _k, cells in _on(calls, tags.id) for cell in cells if cell.values]


async def test_a_named_formula_over_a_rollup_is_worked_out(db):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products, *_reading(products)[3:4])
    orders = await service.update_schema(
        ctx,
        orders.id,
        SchemaUpdate(
            expected_version=orders.schema_version,
            columns=[
                *(ColumnInput.model_validate(item.model_dump()) for item in orders.columns),
                column("Doubled", "formula", formula="{Sum} * 2"),
            ],
        ),
    )
    await insert_rows(db, orders, [{cid(orders, "Items"): [ids["Atlas"], ids["Quill"]]}])
    bound = await bound_view(db, ctx, orders.id)

    read = await _read(service, ctx, bound, [uuid.UUID(cid(orders, "Doubled"))])

    assert read.records[0]["Doubled"] == 71


async def test_every_statement_on_the_read_path_is_armed(db, monkeypatch):
    service, ctx, _org = await _setup(db)
    products, ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products, *_reading(products)[:2])
    await insert_rows(db, orders, [{cid(orders, "Items"): [ids["Atlas"]]} for _ in range(3)])
    view = await TableViewService(db).create_view(
        ctx, orders.id, TableViewCreate(name="All", kind="table")
    )
    await db.flush()
    events: list[str] = []
    real_arm = ReadDeadline.arm

    async def arm(self, session):
        events.append("ARM")
        await real_arm(self, session)

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        events.append(statement)

    monkeypatch.setattr(ReadDeadline, "arm", arm)
    sync_engine = db.get_bind()
    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        deadline = _deadline()
        bound = await TableViewService(db).find_view(ctx, view.id, deadline=deadline)
        read = await _read(
            service,
            ctx,
            bound,
            [uuid.UUID(cid(orders, "Names")), uuid.UUID(cid(orders, "Kinds"))],
            deadline=deadline,
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)

    assert len(read.records) == 3 and read.records[0]["Names"] == ["Atlas"]
    statements = [item for item in events if item != "ARM"]
    assert len([item for item in statements if "set_config" not in item]) >= 8
    for index, item in enumerate(events):
        if item == "ARM" or "set_config" in item:
            continue
        assert events[index - 2 : index] == ["ARM", events[index - 1]], item
        assert "set_config" in events[index - 1], item


async def test_read_bound_reads_no_linked_rows_for_records_linking_to_none(db, monkeypatch):
    service, ctx, _org = await _setup(db)
    products, _ids = await _products(service, ctx)
    orders = await _orders(service, ctx, products, *_reading(products)[:3])
    await insert_rows(db, orders, [{cid(orders, "Ref"): "none"}])
    bound = await bound_view(db, ctx, orders.id)
    calls = _spy(monkeypatch, virtual_table_repo, "get_record_cells_by_ids")
    named = [uuid.UUID(cid(orders, label)) for label in ("Items", "Names", "Count")]

    read = await _read(service, ctx, bound, named)

    assert read.records[0] | {"id": None} == {"id": None, "Items": [], "Names": None, "Count": 0}
    assert not _on(calls, products.id)


async def test_linked_rows_loaded_in_one_chunk_still_count_in_the_next(db, monkeypatch):
    """A linked record shapes to a short label, so what loading it took must not be forgotten
    when the next chunk's room is worked out: one load would otherwise hold the linked
    records counted earlier (free to reference again) and as many new ones again."""
    service, ctx, _org = await _setup(db)
    products = await service.create_table(
        ctx, TableCreate(name="Long names", visibility="org", columns=[column("Name", "long_text")])
    )
    product_ids = await insert_rows(
        db, products, [{cid(products, "Name"): f"{n:04}" + "n" * 9_000} for n in range(400)]
    )
    orders = await _orders(service, ctx, products)
    await insert_rows(
        db,
        orders,
        [
            {
                cid(orders, "Items"): [
                    str(product_id),
                    *([str(product_ids[n - 200])] if n >= 200 else []),
                ]
            }
            for n, product_id in enumerate(product_ids)
        ],
    )
    bound = await bound_view(db, ctx, orders.id)
    calls = _spy(monkeypatch, virtual_table_repo, "get_record_cells_by_ids")
    max_bytes = 2_000_000

    read = await _read(service, ctx, bound, [uuid.UUID(cid(orders, "Items"))], max_bytes=max_bytes)

    loads = [
        sum(shaped_size(cell.values) for cell in cells)
        for _args, _kwargs, cells in _on(calls, products.id)
    ]
    assert read.stopped_by == "bytes"
    assert 200 < len(read.records) < 400
    assert len(loads) == 2
    assert all(load <= max_bytes for load in loads), loads
    assert sum(loads) <= 2 * max_bytes
