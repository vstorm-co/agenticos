"""How a page query is said in words: the one wording publish and consent read.

`tests/integration/test_artifact_bindings.py` resolves real queries; this pins what
`disclose` says of one built by hand, including what a resolved query never holds
today - an order by a worked-out column - so the disclosure cannot drop it silently.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.schemas.artifact import ArtifactBinding, BindingReach
from app.schemas.virtual_table import ColumnDef, OptionDef, RecordFilter, RecordRead, RecordSort
from app.services.artifact_bindings import (
    Unavailable,
    bound_fields,
    describe,
    disclose,
    page_source,
    shape_for,
)
from app.services.virtual_tables import TableSource


def _people() -> tuple[TableSource, dict[str, uuid.UUID]]:
    ids = {label: uuid.uuid4() for label in ("Name", "Salary", "Level", "Pay band")}
    columns = [
        ColumnDef(id=ids["Name"], label="Name", type="text"),
        ColumnDef(id=ids["Salary"], label="Salary", type="number"),
        ColumnDef(id=ids["Level"], label="Level", type="integer"),
        ColumnDef(
            id=ids["Pay band"], label="Pay band", type="formula", formula="{Salary} * {Level}"
        ),
    ]
    return TableSource(id=uuid.uuid4(), name="People", archived=False, columns=columns), ids


def _binding(source: TableSource, ids: dict[str, uuid.UUID], sort: RecordSort) -> ArtifactBinding:
    return ArtifactBinding(
        name="people",
        table_id=source.id,
        sort=sort,
        limit=100,
        fields={"name": ids["Name"]},
        reach=BindingReach(tables={source.id: dict.fromkeys(ids.values(), 0)}),
    )


def test_an_order_by_a_worked_out_column_says_what_it_reads():
    source, ids = _people()
    binding = _binding(source, ids, RecordSort(by=str(ids["Pay band"]), direction="desc"))

    said = disclose(binding, {source.id: source})

    assert said.sort == "Pay band (formula over Salary, Level), descending"
    assert said.fields == {"name": "Name (text)"}


def test_an_order_by_a_column_of_values_names_only_the_column():
    source, ids = _people()

    said = disclose(_binding(source, ids, RecordSort(by=str(ids["Salary"]))), {source.id: source})

    assert said.sort == "Salary, ascending"


def test_an_order_by_a_record_time_says_which():
    source, ids = _people()

    said = disclose(
        _binding(source, ids, RecordSort(by="updated_at", direction="desc")), {source.id: source}
    )

    assert said.sort == "when last changed, descending"


def _deals() -> tuple[TableSource, TableSource, ArtifactBinding]:
    """Deals, linked to Customers, with a select, a lookup and the two rollups."""
    ids = {
        label: uuid.uuid4()
        for label in ("Stage", "Customer", "Name", "Region", "Amount", "Open", "Total", "Count")
    }
    won, lost = uuid.uuid4(), uuid.uuid4()
    customers = TableSource(
        id=uuid.uuid4(),
        name="Customers",
        archived=False,
        columns=[
            ColumnDef(id=ids["Name"], label="Name", type="text"),
            ColumnDef(id=ids["Amount"], label="Spend", type="number"),
        ],
    )
    deals = TableSource(
        id=uuid.uuid4(),
        name="Deals",
        archived=False,
        columns=[
            ColumnDef(
                id=ids["Stage"],
                label="Stage",
                type="single_select",
                options=[OptionDef(id=won, label="Won"), OptionDef(id=lost, label="Lost")],
            ),
            ColumnDef(
                id=ids["Customer"], label="Customer", type="link", link_table_id=customers.id
            ),
            ColumnDef(
                id=ids["Region"],
                label="Region",
                type="lookup",
                link_column_id=ids["Customer"],
                target_column_id=ids["Name"],
            ),
            ColumnDef(
                id=ids["Total"],
                label="Total",
                type="rollup",
                link_column_id=ids["Customer"],
                target_column_id=ids["Amount"],
                aggregate="sum",
            ),
            ColumnDef(
                id=ids["Count"],
                label="Count",
                type="rollup",
                link_column_id=ids["Customer"],
                aggregate="count",
            ),
            ColumnDef(id=ids["Open"], label="Open", type="boolean"),
        ],
    )
    binding = ArtifactBinding(
        name="deals",
        table_id=deals.id,
        filters=[
            RecordFilter(column_id=ids["Stage"], op="in", value=[str(won), str(lost)]),
            RecordFilter(column_id=ids["Stage"], op="eq", value=str(won)),
            RecordFilter(column_id=ids["Open"], op="is_null", value=True),
        ],
        sort=RecordSort(by=str(ids["Total"]), direction="desc"),
        limit=50,
        fields={
            "stage": ids["Stage"],
            "customer": ids["Customer"],
            "region": ids["Region"],
            "total": ids["Total"],
            "count": ids["Count"],
        },
        reach=BindingReach(
            tables={deals.id: {ids["Stage"]: 0}, customers.id: {ids["Name"]: 0}},
            named_by={customers.id: ids["Name"]},
        ),
    )
    return deals, customers, binding


def test_a_query_is_described_in_parts_and_worded_from_them():
    deals, customers, binding = _deals()
    sources = {deals.id: deals, customers.id: customers}

    parts = describe(binding, sources)
    said = disclose(binding, sources)

    assert (parts.table, parts.limit, parts.linked) == ("Deals", 50, ["Customers"])
    assert [(item.column, item.op, item.value) for item in parts.filters] == [
        ("Stage", "in", ["Won", "Lost"]),
        ("Stage", "eq", "Won"),
        ("Open", "is_null", True),
    ]
    assert (parts.sort.column, parts.sort.direction) == ("Total", "desc")
    assert parts.sort.derived is not None
    assert (parts.sort.derived.kind, parts.sort.derived.aggregate) == ("rollup", "sum")
    kinds = {item.name: item.derived for item in parts.fields}
    assert kinds["stage"] is None
    assert (kinds["customer"].kind, kinds["customer"].table, kinds["customer"].column) == (
        "link",
        "Customers",
        "Name",
    )
    assert (kinds["region"].kind, kinds["region"].column) == ("lookup", "Name")
    assert (kinds["count"].kind, kinds["count"].aggregate, kinds["count"].column) == (
        "rollup",
        "count",
        None,
    )
    assert said.filters == ['Stage is one of "Won", "Lost"', 'Stage is "Won"', "Open is empty"]
    assert said.sort == "Total (rollup sum of Customers -> Spend), descending"
    assert said.fields["customer"] == "Customer: link, labels from Customers -> Name"
    assert said.fields["region"] == "Region: lookup of Customers -> Name"
    assert said.fields["count"] == "Count: rollup count of Customers"


def test_a_link_labelled_by_nothing_says_record_ids_and_a_formula_without_inputs_says_so():
    deals, customers, binding = _deals()
    bare = binding.model_copy(update={"reach": BindingReach(tables=binding.reach.tables)})
    sources = {deals.id: deals, customers.id: customers}

    assert disclose(bare, sources).fields["customer"] == (
        "Customer: link, labels from Customers -> record ids"
    )
    source, ids = _people()
    lonely = source.columns[3].model_copy(update={"formula": "1 + 1"})
    source = replace(source, columns=[*source.columns[:3], lonely])
    said = disclose(_binding(source, ids, RecordSort(by=str(ids["Pay band"]))), {source.id: source})
    assert said.sort == "Pay band (formula), ascending"
    parts = describe(_binding(source, ids, RecordSort(by="created_at")), {source.id: source})
    assert (parts.sort.record_time, parts.linked) == ("created_at", [])


def _record(values: dict[str, object]) -> RecordRead:
    return RecordRead(
        id=uuid.uuid4(),
        table_id=uuid.uuid4(),
        schema_version=1,
        values=values,
        revision=1,
        created_at=datetime.now(UTC),
    )


def test_a_field_whose_column_is_archived_or_gone_reads_nothing():
    kept = ColumnDef(id=uuid.uuid4(), label="Name", type="text")
    archived = ColumnDef(id=uuid.uuid4(), label="Old", type="text", archived=True)
    gone = uuid.uuid4()
    record = _record({str(kept.id): "Ada", str(archived.id): "kept in storage"})

    shaped = shape_for([kept, archived], {"name": kept.id, "old": archived.id, "gone": gone})(
        record
    )

    assert shaped == {"id": str(record.id), "name": "Ada", "old": None, "gone": None}


def test_a_bound_field_says_when_its_column_is_archived_or_missing():
    kept = ColumnDef(id=uuid.uuid4(), label="Name", type="text")
    archived = ColumnDef(id=uuid.uuid4(), label="Old", type="text", archived=True)

    described = bound_fields(
        [kept, archived], {"name": kept.id, "old": archived.id, "gone": uuid.uuid4()}
    )

    assert {field: (item.label, item.type, item.state) for field, item in described.items()} == {
        "name": ("Name", "text", "ok"),
        "old": ("Old", "text", "archived"),
        "gone": ("gone", "text", "missing"),
    }


@pytest.mark.anyio
class TestThePageSource:
    """The binding's table as its owner reads it now, or the one reason it reads nothing."""

    OWNER = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")

    def _bound(self) -> tuple[ArtifactBinding, dict[uuid.UUID, TableSource]]:
        source, ids = _people()
        return _binding(source, ids, RecordSort(by="created_at")), {source.id: source}

    async def _read(
        self, binding: ArtifactBinding, sources: dict[uuid.UUID, TableSource]
    ) -> TableSource | Unavailable:
        async def table_source(_person: AuthContext, table_id: uuid.UUID, **_kw: object):
            if table_id not in sources:
                raise NotFoundError(message="Table not found")
            return sources[table_id]

        service = MagicMock()
        service.table_source = AsyncMock(side_effect=table_source)
        return await page_source(service, self.OWNER, binding, deadline=MagicMock())

    async def test_a_table_as_it_was_resolved_is_served(self):
        binding, sources = self._bound()
        name = next(
            column for column in sources[binding.table_id].columns if column.label == "Name"
        )
        binding.reach.named_by[binding.table_id] = name.id

        assert await self._read(binding, sources) == sources[binding.table_id]

    async def test_a_table_the_owner_cannot_read_serves_nothing(self):
        binding, _sources = self._bound()

        assert await self._read(binding, {}) == Unavailable("creator_lost_access")

    async def test_an_archived_table_names_itself(self):
        binding, sources = self._bound()
        sources[binding.table_id] = replace(sources[binding.table_id], archived=True)

        assert await self._read(binding, sources) == Unavailable("source_changed", "People")

    async def test_a_reached_column_that_is_gone_names_the_table(self):
        binding, sources = self._bound()
        binding.reach.tables[binding.table_id][uuid.uuid4()] = 0

        assert await self._read(binding, sources) == Unavailable("source_changed", "People")

    @pytest.mark.parametrize("change", ["archived", "revision"])
    async def test_a_reached_column_archived_or_revised_names_the_column(self, change):
        binding, sources = self._bound()
        source = sources[binding.table_id]
        columns = [
            column.model_copy(
                update={"archived": True} if change == "archived" else {"revision": 7}
            )
            if column.label == "Salary"
            else column
            for column in source.columns
        ]
        sources[binding.table_id] = replace(source, columns=columns)

        assert await self._read(binding, sources) == Unavailable("source_changed", "Salary")

    @pytest.mark.parametrize("stored", [uuid.uuid4(), None])
    async def test_a_table_naming_its_records_by_another_column_names_the_table(self, stored):
        binding, sources = self._bound()
        binding.reach.named_by[binding.table_id] = stored

        assert await self._read(binding, sources) == Unavailable("source_changed", "People")
