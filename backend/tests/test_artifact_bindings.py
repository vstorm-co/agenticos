"""How a page query is said in words: the one wording publish and consent read.

`tests/integration/test_artifact_bindings.py` resolves real queries; this pins what
`disclose` says of one built by hand, including what a resolved query never holds
today - an order by a worked-out column - so the disclosure cannot drop it silently.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from app.schemas.artifact import ArtifactBinding, BindingReach
from app.schemas.virtual_table import ColumnDef, OptionDef, RecordFilter, RecordSort
from app.services.artifact_bindings import describe, disclose
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
