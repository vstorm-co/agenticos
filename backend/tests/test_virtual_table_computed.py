"""What naming a column makes a reader read: a formula's inputs, a rollup's link, a linked table."""

from uuid import UUID

from app.schemas.virtual_table import ColumnDef
from app.services.virtual_tables import Reach, reach

OTHER_TABLE = UUID("00000000-0000-4000-8000-0000000000f1")
AMOUNT = UUID("00000000-0000-4000-8000-0000000000f2")

LINK = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000001"),
    label="Invoices",
    type="link",
    link_table_id=OTHER_TABLE,
)
TOTAL = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000002"),
    label="Total",
    type="rollup",
    link_column_id=LINK.id,
    target_column_id=AMOUNT,
    aggregate="sum",
)
COUNT = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000003"),
    label="Invoice count",
    type="rollup",
    link_column_id=LINK.id,
    aggregate="count",
)
QUANTITY = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000004"), label="Quantity", type="integer"
)
GONE = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000005"), label="Gone", type="number", archived=True
)
FORMULA = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000006"),
    label="Score",
    type="formula",
    formula="{Total} * {Quantity} + {Gone} + {total}",
)
NAME = ColumnDef(id=UUID("00000000-0000-4000-8000-000000000007"), label="Name", type="text")
COLUMNS = [LINK, TOTAL, COUNT, QUANTITY, GONE, FORMULA, NAME]


def test_reach_follows_a_formula_into_a_rollup_and_its_link():
    # `{Gone}` names an archived column and `{total}` no live label exactly, so
    # neither is read - the way `check_formula` matches a formula's labels.
    reached = reach(COLUMNS, [FORMULA.id, TOTAL.id])

    assert reached == Reach(
        columns=frozenset({FORMULA.id, TOTAL.id, QUANTITY.id, LINK.id}),
        linked={OTHER_TABLE: frozenset({AMOUNT})},
    )


def test_reach_of_a_count_rollup_reads_no_target():
    reached = reach(COLUMNS, [COUNT.id])

    assert reached.columns == frozenset({COUNT.id, LINK.id})
    assert reached.linked == {OTHER_TABLE: frozenset()}


def test_reach_of_a_named_link_names_its_table():
    reached = reach(COLUMNS, [LINK.id, NAME.id])

    assert reached.columns == frozenset({LINK.id, NAME.id})
    assert reached.linked == {OTHER_TABLE: frozenset()}


def test_reach_follows_nothing_from_what_is_not_a_column():
    unknown = UUID("00000000-0000-4000-8000-0000000000e1")
    stray = ColumnDef(
        id=UUID("00000000-0000-4000-8000-000000000008"),
        label="Stray",
        type="lookup",
        link_column_id=unknown,
        target_column_id=AMOUNT,
    )

    reached = reach([*COLUMNS, stray], [stray.id])

    assert reached == Reach(columns=frozenset({stray.id, unknown}), linked={})


def test_rollups_return_json_safe_values_when_finite_inputs_overflow_the_sum():
    import json

    from app.services.virtual_tables.computed import _Linked, _work_out

    amount = ColumnDef(id=AMOUNT, label="Amount", type="number")
    linked = _Linked(
        columns=[amount],
        values={
            "a": {str(AMOUNT): 1e308},
            "b": {str(AMOUNT): 1e308},
        },
        names={},
    )
    assert _work_out(TOTAL, ["a", "b"], linked) is None
    average = TOTAL.model_copy(update={"aggregate": "avg"})
    assert _work_out(average, ["a", "b"], linked) == 1e308
    json.dumps(
        {
            "sum": _work_out(TOTAL, ["a", "b"], linked),
            "avg": _work_out(average, ["a", "b"], linked),
        },
        allow_nan=False,
    )
