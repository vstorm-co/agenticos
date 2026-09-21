"""Record operations against a real database: typing, revisions, history, events, listing."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.db.models.resource_grant import GrantLevel
from app.db.models.virtual_table import (
    VirtualTableOutbox,
    VirtualTableRecord,
    VirtualTableRecordHistory,
)
from app.repositories import resource_grant_repo
from app.schemas.virtual_table import (
    OptionInput,
    RecordCreate,
    RecordFilter,
    RecordQuery,
    RecordSort,
    RecordUpdate,
    RecordUpsert,
    SchemaUpdate,
    TableCreate,
)
from app.services.access import TABLE
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables.exceptions import (
    InvalidQueryError,
    InvalidRecordError,
    RevisionConflictError,
    RevisionRequiredError,
)
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
    return service, ctx, await orders_table(service, ctx), org


async def _count(db, model, **where) -> int:
    query = select(func.count()).select_from(model)
    for field, value in where.items():
        query = query.where(getattr(model, field) == value)
    return await db.scalar(query)


async def test_a_created_record_has_revision_one_history_and_one_created_event(db):
    service, ctx, table, org = await _setup(db)
    customer = cid(table, "Customer")

    written = await service.create_record(
        ctx, table.id, RecordCreate(external_id="A-1", values={customer: "  Acme  "})
    )

    assert written.created and not written.replayed
    assert written.record.revision == 1 and written.record.schema_version == 1
    assert written.record.values == {customer: "  Acme  "}
    history = (await db.scalars(select(VirtualTableRecordHistory))).all()
    assert [(h.operation, h.revision, h.before) for h in history] == [("create", 1, None)]
    events = (await db.scalars(select(VirtualTableOutbox))).all()
    assert len(events) == 1
    assert events[0].event_type == "table.record.created"
    assert events[0].payload["record_id"] == str(written.record.id)
    assert events[0].dispatched_at is None
    assert events[0].organization_id == org.id


async def test_get_exists_and_lookup_by_external_id(db):
    service, ctx, table, _org = await _setup(db)
    written = await service.create_record(ctx, table.id, RecordCreate(external_id="A-1", values={}))

    assert (await service.get_record(ctx, table.id, written.record.id)).external_id == "A-1"
    assert (await service.get_record_by_external_id(ctx, table.id, "A-1")).id == written.record.id
    assert await service.record_exists(ctx, table.id, "A-1") is True
    assert await service.record_exists(ctx, table.id, "nope") is False
    with pytest.raises(NotFoundError):
        await service.get_record(ctx, table.id, uuid.uuid4())
    with pytest.raises(NotFoundError):
        await service.get_record_by_external_id(ctx, table.id, "nope")


async def test_a_taken_external_id_is_a_conflict_and_an_untaken_one_may_repeat_as_null(db):
    service, ctx, table, _org = await _setup(db)
    await service.create_record(ctx, table.id, RecordCreate(external_id="A-1", values={}))

    with pytest.raises(AlreadyExistsError):
        await service.create_record(ctx, table.id, RecordCreate(external_id="A-1", values={}))
    await service.create_record(ctx, table.id, RecordCreate(values={}))
    await service.create_record(ctx, table.id, RecordCreate(values={}))
    assert await _count(db, VirtualTableRecord) == 3


async def test_invalid_values_are_refused_per_field_and_nothing_is_written(db):
    service, ctx, table, _org = await _setup(db)
    quantity, paid = cid(table, "Quantity"), cid(table, "Paid")
    stray = str(uuid.uuid4())

    with pytest.raises(InvalidRecordError) as raised:
        await service.create_record(
            ctx,
            table.id,
            RecordCreate(values={quantity: "many", paid: "yes", stray: 1}),
        )

    fields = {item["field"] for item in raised.value.details["fields"]}
    assert fields == {f"values.{quantity}", f"values.{paid}", f"values.{stray}"}
    assert await _count(db, VirtualTableRecord) == 0
    assert await _count(db, VirtualTableOutbox) == 0


async def test_every_column_type_round_trips_its_value(db):
    service, ctx, table, _org = await _setup(db)
    status = next(c for c in table.columns if c.label == "Status").options[0].id
    tags = [option.id for option in next(c for c in table.columns if c.label == "Tags").options]
    values = {
        cid(table, "Customer"): "Zażółć  gęślą\n",
        cid(table, "Quantity"): 3,
        cid(table, "Total"): 19.5,
        cid(table, "Paid"): False,
        cid(table, "Due"): "2026-10-01",
        cid(table, "Placed"): "2026-09-21T10:00:00+02:00",
        cid(table, "Status"): str(status),
        cid(table, "Tags"): [str(tag) for tag in tags],
    }

    written = await service.create_record(ctx, table.id, RecordCreate(values=values))

    stored = (await service.get_record(ctx, table.id, written.record.id)).values
    assert stored[cid(table, "Placed")] == "2026-09-21T08:00:00.000000+00:00"
    assert stored == {**values, cid(table, "Placed"): "2026-09-21T08:00:00.000000+00:00"}


async def test_an_update_changes_named_cells_bumps_the_revision_and_keeps_history(db):
    service, ctx, table, _org = await _setup(db)
    customer, quantity = cid(table, "Customer"), cid(table, "Quantity")
    written = await service.create_record(
        ctx, table.id, RecordCreate(values={customer: "Acme", quantity: 1})
    )

    changed = await service.update_record(
        ctx,
        table.id,
        written.record.id,
        RecordUpdate(expected_revision=1, values={quantity: 2, customer: None}),
    )

    assert changed.record.revision == 2 and not changed.created
    assert changed.record.values == {quantity: 2}
    assert changed.record.updated_at is not None
    history = (
        await db.scalars(
            select(VirtualTableRecordHistory).order_by(VirtualTableRecordHistory.revision)
        )
    ).all()
    assert [h.operation for h in history] == ["create", "update"]
    assert history[1].before == {customer: "Acme", quantity: 1}
    assert history[1].after == {quantity: 2}
    assert await _count(db, VirtualTableOutbox) == 1


async def test_a_stale_revision_is_a_typed_conflict_and_the_record_is_untouched(db):
    service, ctx, table, _org = await _setup(db)
    quantity = cid(table, "Quantity")
    written = await service.create_record(ctx, table.id, RecordCreate(values={quantity: 1}))
    await service.update_record(
        ctx, table.id, written.record.id, RecordUpdate(expected_revision=1, values={quantity: 2})
    )

    with pytest.raises(RevisionConflictError) as raised:
        await service.update_record(
            ctx,
            table.id,
            written.record.id,
            RecordUpdate(expected_revision=1, values={quantity: 99}),
        )
    with pytest.raises(RevisionConflictError):
        await service.delete_record(ctx, table.id, written.record.id, expected_revision=1)

    assert raised.value.status_code == 409
    assert raised.value.details == {
        "record_id": written.record.id,
        "expected_revision": 1,
        "current_revision": 2,
    }
    assert (await service.get_record(ctx, table.id, written.record.id)).values == {quantity: 2}


async def test_a_delete_removes_the_record_and_keeps_its_history(db):
    service, ctx, table, _org = await _setup(db)
    customer = cid(table, "Customer")
    written = await service.create_record(ctx, table.id, RecordCreate(values={customer: "Acme"}))

    await service.delete_record(ctx, table.id, written.record.id, expected_revision=1)

    with pytest.raises(NotFoundError):
        await service.get_record(ctx, table.id, written.record.id)
    with pytest.raises(NotFoundError):
        await service.delete_record(ctx, table.id, written.record.id, expected_revision=1)
    history = (
        await db.scalars(
            select(VirtualTableRecordHistory).order_by(VirtualTableRecordHistory.revision)
        )
    ).all()
    assert [h.operation for h in history] == ["create", "delete"]
    assert history[1].before == {customer: "Acme"} and history[1].after is None


async def test_an_upsert_creates_then_requires_the_revision_to_update(db):
    service, ctx, table, _org = await _setup(db)
    customer = cid(table, "Customer")

    first = await service.upsert_record(
        ctx, table.id, "A-1", RecordUpsert(values={customer: "Acme"})
    )
    assert first.created and first.record.revision == 1 and first.record.external_id == "A-1"

    with pytest.raises(RevisionRequiredError) as missing:
        await service.upsert_record(ctx, table.id, "A-1", RecordUpsert(values={customer: "Acme 2"}))
    assert missing.value.status_code == 428
    assert missing.value.details == {"record_id": first.record.id, "current_revision": 1}

    with pytest.raises(RevisionConflictError):
        await service.upsert_record(
            ctx, table.id, "A-1", RecordUpsert(values={customer: "x"}, expected_revision=7)
        )

    second = await service.upsert_record(
        ctx, table.id, "A-1", RecordUpsert(values={customer: "Acme 2"}, expected_revision=1)
    )
    assert not second.created
    assert second.record.id == first.record.id and second.record.revision == 2
    assert await _count(db, VirtualTableRecord) == 1
    assert await _count(db, VirtualTableOutbox) == 1


async def test_an_updated_record_does_not_emit_a_second_created_event(db):
    service, ctx, table, _org = await _setup(db)
    written = await service.create_record(ctx, table.id, RecordCreate(values={}))
    await service.update_record(
        ctx, table.id, written.record.id, RecordUpdate(expected_revision=1, values={})
    )
    assert await _count(db, VirtualTableOutbox) == 1


async def _seed(service, ctx, table, rows):
    quantity, customer = cid(table, "Quantity"), cid(table, "Customer")
    for external_id, name, qty in rows:
        values = {customer: name}
        if qty is not None:
            values[quantity] = qty
        await service.create_record(
            ctx, table.id, RecordCreate(external_id=external_id, values=values)
        )


async def test_a_listing_is_ordered_and_a_page_never_repeats_or_skips_a_record(db):
    service, ctx, table, _org = await _setup(db)
    await _seed(service, ctx, table, [(f"r{i}", f"c{i}", i % 3) for i in range(7)])
    quantity = cid(table, "Quantity")

    by_quantity = RecordSort(by=quantity, direction="desc")
    everything = await service.list_records(ctx, table.id, RecordQuery(sort=by_quantity, limit=100))
    pages = []
    for skip in (0, 3, 6):
        page = await service.list_records(
            ctx, table.id, RecordQuery(sort=by_quantity, skip=skip, limit=3)
        )
        pages.extend(item.id for item in page.items)
    again = await service.list_records(ctx, table.id, RecordQuery(sort=by_quantity, limit=100))

    assert pages == [item.id for item in everything.items] == [item.id for item in again.items]
    assert len(set(pages)) == 7
    quantities = [item.values[quantity] for item in everything.items]
    assert quantities == sorted(quantities, reverse=True)
    first = await service.list_records(ctx, table.id, RecordQuery(limit=3))
    assert first.has_more is True and (first.skip, first.limit) == (0, 3)
    last = await service.list_records(ctx, table.id, RecordQuery(skip=6, limit=3))
    assert last.has_more is False and len(last.items) == 1


async def test_records_without_a_value_sort_last_in_either_direction(db):
    service, ctx, table, _org = await _setup(db)
    await _seed(service, ctx, table, [("a", "a", 5), ("b", "b", None), ("c", "c", 1)])
    quantity = cid(table, "Quantity")

    for direction, expected in (("asc", [1, 5, None]), ("desc", [5, 1, None])):
        page = await service.list_records(
            ctx, table.id, RecordQuery(sort=RecordSort(by=quantity, direction=direction))
        )
        assert [item.values.get(quantity) for item in page.items] == expected


async def test_the_default_order_is_creation_time_then_id_and_updated_at_is_sortable(db):
    service, ctx, table, _org = await _setup(db)
    await _seed(service, ctx, table, [("a", "a", 1), ("b", "b", 1), ("c", "c", 1)])

    default = await service.list_records(ctx, table.id)
    keys = [(item.created_at, item.id) for item in default.items]
    assert keys == sorted(keys)
    edited = await service.update_record(
        ctx, table.id, default.items[0].id, RecordUpdate(expected_revision=1, values={})
    )
    newest = await service.list_records(
        ctx, table.id, RecordQuery(sort=RecordSort(by="updated_at", direction="desc"))
    )
    assert newest.items[0].id == edited.record.id


async def _ids(service, ctx, table, *filters) -> set[str]:
    page = await service.list_records(ctx, table.id, RecordQuery(filters=list(filters)))
    return {item.external_id for item in page.items}


async def test_typed_filters_compare_numbers_dates_times_text_booleans_and_options(db):
    service, ctx, table, _org = await _setup(db)
    status = next(c for c in table.columns if c.label == "Status")
    tags = next(c for c in table.columns if c.label == "Tags")
    rows = [
        (
            "a",
            {
                "Customer": "Acme Ltd",
                "Quantity": 1,
                "Total": 10.5,
                "Paid": True,
                "Due": "2026-01-01",
                "Placed": "2026-01-01T10:00:00Z",
                "Status": str(status.options[0].id),
                "Tags": [str(tags.options[0].id)],
            },
        ),
        (
            "b",
            {
                "Customer": "50% off_Co",
                "Quantity": 5,
                "Total": 99,
                "Paid": False,
                "Due": "2026-06-01",
                "Placed": "2026-06-01T10:00:00Z",
                "Status": str(status.options[1].id),
                "Tags": [],
            },
        ),
        ("c", {}),
    ]
    for external_id, cells in rows:
        await service.create_record(
            ctx,
            table.id,
            RecordCreate(
                external_id=external_id, values={cid(table, k): v for k, v in cells.items()}
            ),
        )

    def where(label, op, value):
        return RecordFilter(
            column_id=next(c.id for c in table.columns if c.label == label), op=op, value=value
        )

    assert await _ids(service, ctx, table, where("Quantity", "gte", 5)) == {"b"}
    assert await _ids(service, ctx, table, where("Quantity", "eq", 1)) == {"a"}
    assert await _ids(service, ctx, table, where("Quantity", "in", [1, 5])) == {"a", "b"}
    assert await _ids(service, ctx, table, where("Quantity", "ne", 1)) == {"b"}
    assert await _ids(service, ctx, table, where("Total", "lt", 50.25)) == {"a"}
    assert await _ids(service, ctx, table, where("Paid", "eq", False)) == {"b"}
    assert await _ids(service, ctx, table, where("Due", "gt", "2026-03-01")) == {"b"}
    assert await _ids(service, ctx, table, where("Due", "lte", "2026-01-01")) == {"a"}
    assert await _ids(service, ctx, table, where("Placed", "lt", "2026-03-01T00:00:00+00:00")) == {
        "a"
    }
    assert await _ids(service, ctx, table, where("Customer", "contains", "acme")) == {"a"}
    assert await _ids(service, ctx, table, where("Customer", "contains", "%")) == {"b"}
    assert await _ids(service, ctx, table, where("Customer", "contains", "f_C")) == {"b"}
    assert await _ids(service, ctx, table, where("Customer", "contains", "_")) == {"b"}
    assert await _ids(service, ctx, table, where("Customer", "starts_with", "Acme")) == {"a"}
    assert await _ids(service, ctx, table, where("Customer", "eq", "Acme Ltd")) == {"a"}
    assert await _ids(service, ctx, table, where("Customer", "in", ["Acme Ltd", "x"])) == {"a"}
    assert await _ids(service, ctx, table, where("Status", "eq", str(status.options[1].id))) == {
        "b"
    }
    assert await _ids(service, ctx, table, where("Status", "in", [str(status.options[0].id)])) == {
        "a"
    }
    assert await _ids(service, ctx, table, where("Tags", "contains", str(tags.options[0].id))) == {
        "a"
    }
    assert await _ids(service, ctx, table, where("Quantity", "is_null", True)) == {"c"}
    assert await _ids(service, ctx, table, where("Quantity", "is_null", False)) == {"a", "b"}
    assert await _ids(
        service, ctx, table, where("Quantity", "gte", 1), where("Paid", "eq", True)
    ) == {"a"}


async def test_a_filter_or_sort_the_table_cannot_answer_is_a_typed_refusal(db):
    service, ctx, table, _org = await _setup(db)
    quantity = next(c.id for c in table.columns if c.label == "Quantity")
    tags = next(c.id for c in table.columns if c.label == "Tags")
    cases = [
        (
            RecordQuery(filters=[RecordFilter(column_id=uuid.uuid4(), op="eq", value=1)]),
            "filters.0.column_id",
        ),
        (
            RecordQuery(filters=[RecordFilter(column_id=quantity, op="contains", value="1")]),
            "filters.0",
        ),
        (
            RecordQuery(filters=[RecordFilter(column_id=quantity, op="eq", value="one")]),
            "filters.0",
        ),
        (RecordQuery(sort=RecordSort(by="nonsense")), "sort.by"),
        (RecordQuery(sort=RecordSort(by=str(uuid.uuid4()))), "sort.by"),
        (RecordQuery(sort=RecordSort(by=str(tags))), "sort.by"),
    ]
    for query, field in cases:
        with pytest.raises(InvalidQueryError) as raised:
            await service.list_records(ctx, table.id, query)
        assert raised.value.details["fields"][0]["field"] == field


async def test_records_written_before_a_column_was_archived_can_still_be_filtered_on_it(db):
    service, ctx, table, _org = await _setup(db)
    await _seed(service, ctx, table, [("a", "a", 1), ("b", "b", 2)])
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
    quantity = next(c.id for c in table.columns if c.label == "Quantity")

    page = await service.list_records(
        ctx, table.id, RecordQuery(filters=[RecordFilter(column_id=quantity, op="gt", value=1)])
    )
    assert [item.external_id for item in page.items] == ["b"]


async def test_a_viewer_reads_but_only_an_edit_grant_lets_them_write(db):
    service, ctx, table, org = await _setup(db)
    written = await service.create_record(ctx, table.id, RecordCreate(external_id="A-1", values={}))
    colleague = await make_user(db)
    viewer = ctx_for(colleague, org, "viewer")
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=table.id,
        level=GrantLevel.READ,
    )

    assert (await service.get_record(viewer, table.id, written.record.id)).external_id == "A-1"
    assert (await service.list_records(viewer, table.id)).items
    with pytest.raises(NotFoundError):
        await service.create_record(viewer, table.id, RecordCreate(values={}))
    with pytest.raises(NotFoundError):
        await service.delete_record(viewer, table.id, written.record.id, expected_revision=1)

    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=colleague.id,
        resource_type=TABLE.key,
        resource_id=table.id,
        level=GrantLevel.EDIT,
    )
    await service.create_record(viewer, table.id, RecordCreate(values={}))


async def test_another_organization_cannot_read_or_write_a_table_even_as_an_owner(db):
    service, ctx, table, _org = await _setup(db)
    written = await service.create_record(ctx, table.id, RecordCreate(external_id="A-1", values={}))
    outsider = await make_user(db)
    intruder = ctx_for(outsider, await make_org(db, owner=outsider), "owner")

    calls = [
        service.get_record(intruder, table.id, written.record.id),
        service.get_record_by_external_id(intruder, table.id, "A-1"),
        service.record_exists(intruder, table.id, "A-1"),
        service.list_records(intruder, table.id),
        service.create_record(intruder, table.id, RecordCreate(values={})),
        service.update_record(
            intruder, table.id, written.record.id, RecordUpdate(expected_revision=1, values={})
        ),
        service.upsert_record(intruder, table.id, "A-1", RecordUpsert(values={})),
        service.delete_record(intruder, table.id, written.record.id, expected_revision=1),
    ]
    for call in calls:
        with pytest.raises(NotFoundError):
            await call
    assert await _count(db, VirtualTableRecord) == 1
    assert (await service.get_record(ctx, table.id, written.record.id)).revision == 1


async def test_a_record_id_from_another_table_is_not_found_through_this_one(db):
    service, ctx, table, _org = await _setup(db)
    other = await service.create_table(
        ctx, TableCreate(name="Other", columns=[column("A", "text")])
    )
    written = await service.create_record(ctx, table.id, RecordCreate(values={}))

    with pytest.raises(NotFoundError):
        await service.get_record(ctx, other.id, written.record.id)
    with pytest.raises(NotFoundError):
        await service.delete_record(ctx, other.id, written.record.id, expected_revision=1)
