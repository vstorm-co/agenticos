"""Formula columns: what a formula may say, and what it works out for a record."""

import uuid
from datetime import UTC, datetime

import pytest

from app.schemas.virtual_table import ColumnDef, ColumnTypeName, OptionDef
from app.services.virtual_tables.formula import (
    MAX_DEPTH,
    MAX_FORMULA,
    MAX_TEXT,
    FormulaProblem,
    check_formula,
    references,
    rename_references,
    work_out,
)


def _column(label: str, type_: ColumnTypeName = "number", **rest) -> ColumnDef:
    return ColumnDef(id=uuid.uuid4(), label=label, type=type_, **rest)


STAGE_OPEN = OptionDef(id=uuid.uuid4(), label="Open")
STAGE_WON = OptionDef(id=uuid.uuid4(), label="Won")
PRICE = _column("Price")
QUANTITY = _column("Quantity", "integer")
NAME = _column("Name", "text")
DUE = _column("Due", "date")
STAGE = _column("Stage", "single_select", options=[STAGE_OPEN, STAGE_WON])
TAGS = _column("Tags", "multi_select", options=[STAGE_OPEN, STAGE_WON])
ITEMS = _column("Items", "link", link_table_id=uuid.uuid4())
GONE = _column("Gone", archived=True)
TOTAL = _column("Total", "formula", formula="{Price} * {Quantity}")
COLUMNS = [PRICE, QUANTITY, NAME, DUE, STAGE, TAGS, ITEMS, GONE, TOTAL]
RECORD = {
    str(PRICE.id): 2.5,
    str(QUANTITY.id): 4,
    str(NAME.id): "Ada",
    str(DUE.id): "2026-01-10",
    str(STAGE.id): str(STAGE_WON.id),
    str(TAGS.id): [str(STAGE_OPEN.id), str(STAGE_WON.id)],
}


def _work_out(formula: str, record: dict | None = None):
    return work_out(formula, COLUMNS, RECORD if record is None else record)


def _check(formula: str) -> None:
    check_formula(formula, _column("New", "formula"), COLUMNS)


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("{Price} * {Quantity}", 10),
        ("({Price} + 0.5) / 2 - 1 % 1", 1.5),
        ("0.1 + 0.2", 0.3),
        ("-{Price}", -2.5),
        ("+{Quantity}", 4),
        ("{Quantity} >= 4 AND NOT ({Price} > 3)", True),
        ("{Quantity} > 9 or false", False),
        ("1 < {Quantity} < 9", True),
        ("1 < {Quantity} < 3", False),
        ("{Name} = 'Ada'", True),
        ("{Name} == 'Ada'", True),
        ("{Name} <> 'Ada'", False),
        ("{Name} < 'Bob'", True),
        ("{Name} <= 'Ada' and {Name} >= 'Ada'", True),
        ('IF({Quantity} > 3, "bulk", "single")', "bulk"),
        ('if({Quantity} > 9, "bulk", "single")', "single"),
        ("IF({Quantity} = 0, 0, 10 / {Quantity})", 2.5),
        ("IF({Quantity} = 4, 0, 10 / 0)", 0),
        ("IF(1 > 2, 10 / 0, 7)", 7),
        ("{Quantity} <> 4 AND 10 / 0 > 1", False),
        ("{Quantity} = 4 OR 10 / 0 > 1", True),
        ("{Quantity} = 4 AND 10 / 1 > 1", True),
        ("{Quantity} <> 4 OR 10 / 1 > 1", True),
        ("ROUND({Price} / 3, 2)", 0.83),
        ("ROUND({Price})", 2),
        ("ABS(-{Quantity})", 4),
        ("MIN({Price}, {Quantity}, 3)", 2.5),
        ("MAX({Price}, {Quantity})", 4),
        ('CONCAT({Name}, " x", {Quantity}, " ", TRUE, " ", 2.0)', "Ada x4 true 2"),
        ("LEN({Name})", 3),
        ("UPPER({Name})", "ADA"),
        ("LOWER('R AND D')", "r and d"),
        ("DAYS('2026-01-15', {Due})", 5),
        ("{Stage} = 'Won'", True),
        ("CONCAT({Tags})", "Open, Won"),
        ('CONCAT("R AND D", " ", {Name})', "R AND D Ada"),
    ],
)
def test_a_formula_works_out_what_it_says(formula, expected):
    _check(formula)
    assert _work_out(formula) == expected


def test_today_is_the_date_in_utc():
    assert _work_out("TODAY()") == datetime.now(UTC).date().isoformat()


@pytest.mark.parametrize(
    "formula",
    [
        "{Price} / 0",
        "{Name} + 1",
        "{Price} + {Gone}",
        "{Price} * {Missing}",
        "{Name} < 3",
        "IF(1, 2)",
        "DAYS({Due})",
        "DAYS({Name}, {Due})",
        "DAYS({Price}, {Due})",
        "MIN()",
        "ROUND()",
        "1e308 * 10",
    ],
)
def test_a_value_it_cannot_work_out_is_no_value(formula):
    assert _work_out(formula) is None


def test_a_cell_left_empty_is_no_value_to_calculate_with():
    assert _work_out("{Price} * {Quantity}", {str(QUANTITY.id): 3}) is None
    assert _work_out("CONCAT({Name}, '!')", {}) == "!"


def test_text_joined_past_the_limit_is_no_value():
    record = {**RECORD, str(NAME.id): "x" * (MAX_TEXT // 2 + 1)}
    assert _work_out("CONCAT({Name}, {Name})", record) is None


def test_an_unchecked_expression_works_out_nothing():
    """What `check_formula` refuses never runs, and a stored one that slipped past
    it still leaves its cell empty rather than raising on a read."""
    assert work_out("b'x'", COLUMNS, RECORD) is None
    assert work_out("[1]", COLUMNS, RECORD) is None


@pytest.mark.parametrize(
    ("formula", "says", "reason"),
    [
        ("{Price} * 1,23", "decimals with a dot", "decimal_comma"),
        ("({Price}, 1)", "decimals with a dot", "decimal_comma"),
        ("", "needs a formula", "empty"),
        ("x" * (MAX_FORMULA + 1), "at most", "too_long"),
        ("{Price} *", "not written correctly", "syntax"),
        ("(", "not written correctly", "syntax"),
        ("{Missing} + 1", "not a live column", "not_a_column"),
        ("{Gone} + 1", "not a live column", "not_a_column"),
        ("{Total} + 1", "formula column", "not_a_value"),
        ("{Items}", "link column", "not_a_value"),
        ("Price + 1", "name a column in braces", "unknown_name"),
        ("{Price} ** 2", "calculates with", "arithmetic"),
        ("{Price} // 2", "calculates with", "arithmetic"),
        ("~{Quantity}", "not one a formula uses", "operator"),
        ("{Quantity} in [1]", "compares with", "comparison"),
        ("__import__('os')", "functions", "function"),
        ("UPPER(**{})", "functions", "function"),
        ("{Name}.upper()", "functions", "function"),
        ("[1, 2]", "can contain", "unsupported"),
        ("{Price}[0]", "can contain", "unsupported"),
        ("lambda: 1", "can contain", "unsupported"),
        ("None", "numbers, text and true or false", "constant"),
        ("b'x'", "numbers, text and true or false", "constant"),
        ("ABS(" * (MAX_DEPTH + 1) + "1" + ")" * (MAX_DEPTH + 1), "nests too deeply", "too_deep"),
    ],
)
def test_a_formula_that_cannot_be_one_is_refused_saying_why(formula, says, reason):
    with pytest.raises(FormulaProblem, match=says) as refused:
        _check(formula)
    assert refused.value.reason == reason


def test_a_refusal_carries_what_its_message_names():
    with pytest.raises(FormulaProblem) as missing:
        _check("{Missing} + 1")
    assert missing.value.params == {"label": "Missing"}
    with pytest.raises(FormulaProblem) as linked:
        _check("{Items}")
    assert linked.value.params == {"label": "Items", "type": "link"}


def test_a_comma_inside_a_call_still_separates_its_arguments():
    _check("ROUND({Price} * 1, 2)")


def test_deep_unary_nesting_is_refused():
    with pytest.raises(FormulaProblem, match="nests too deeply"):
        _check("-" * (MAX_DEPTH + 2) + "1")


def test_references_are_listed_once_in_order_and_renamed_where_named():
    formula = "{ Price } * {Quantity} + {Price}"

    assert references(formula) == ["Price", "Quantity"]
    assert rename_references(formula, {"Price": "Unit price"}) == (
        "{Unit price} * {Quantity} + {Unit price}"
    )
