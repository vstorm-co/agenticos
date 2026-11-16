"""Structured workflow expectations are independent of JSONB key order."""

import pytest

from app.schemas.workflow_eval import EvalExpectation
from app.services.workflow_evals import judge


def test_an_equals_expectation_ignores_key_order() -> None:
    expectation = EvalExpectation(
        kind="equals", field="structured", value='{"name": "Ada", "id": 7}'
    )
    # The step answered {"name": "Ada", "id": 7}; the attempt's `result` is JSONB,
    # which returns the object as {"id": 7, "name": "Ada"}.
    read_back = {"structured": {"id": 7, "name": "Ada"}}
    as_answered = {"structured": {"name": "Ada", "id": 7}}

    matched, _ = judge(expectation, read_back)
    passed, _ = judge(expectation, as_answered)

    assert read_back == as_answered  # the same content
    assert matched is True
    assert passed is True


@pytest.mark.parametrize(
    "kind, actual, expected, matches",
    [
        ("equals", {"nested": {"b": 2, "a": 1}}, '{ "nested": { "a": 1, "b": 2 } }', True),
        ("equals", [1, 2], "[2, 1]", False),
        ("equals", {"value": True}, '{"value": 1}', False),
        ("contains", {"outer": {"b": 2, "a": 1}}, '{"a":1,"b":2}', True),
        ("not_contains", {"outer": {"b": 2, "a": 1}}, '{"a":1,"b":2}', False),
        ("contains", {"message": "Hello Ada"}, "hello", True),
        ("equals", "  HELLO  ", "hello", True),
        ("equals", None, "missing", False),
        ("contains", [1, 2], "1", True),
    ],
)
def test_structured_and_plain_text_comparison_contracts(kind, actual, expected, matches) -> None:
    expectation = EvalExpectation(kind=kind, field="value", value=expected)
    passed, _ = judge(expectation, {"value": actual})
    assert passed is matches
