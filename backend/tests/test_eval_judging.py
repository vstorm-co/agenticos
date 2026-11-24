"""The shared eval judge: what an answer says against what it should say."""

import pytest
from pydantic import ValidationError

from app.schemas.eval_judging import EvalExpectation
from app.services.eval_judging import judge


def _expect(
    kind: str = "contains", field: str | None = "text", value: str = "billing"
) -> EvalExpectation:
    return EvalExpectation(kind=kind, field=field, value=value)  # type: ignore[arg-type]


def test_equals_matches_ignoring_case_and_surrounding_space():
    passed, actual = judge(_expect("equals", value="Billing"), {"text": "  billing "})

    assert passed is True
    assert actual == "  billing "


def test_equals_fails_when_the_answer_says_more():
    passed, _ = judge(_expect("equals", value="billing"), {"text": "billing help"})

    assert passed is False


def test_contains_passes_on_a_substring():
    passed, actual = judge(_expect("contains"), {"text": "See the billing page"})

    assert passed is True
    assert actual == "See the billing page"


def test_contains_fails_when_the_word_is_absent():
    passed, _ = judge(_expect("contains"), {"text": "See the pricing page"})

    assert passed is False


def test_not_contains_passes_when_the_word_is_absent():
    passed, _ = judge(_expect("not_contains", value="draft"), {"text": "Published"})

    assert passed is True


def test_not_contains_fails_when_the_word_is_present():
    passed, _ = judge(_expect("not_contains", value="draft"), {"text": "Saved as draft"})

    assert passed is False


def test_a_null_field_judges_the_whole_output_as_json():
    passed, actual = judge(
        _expect("contains", field=None, value="billing"), {"category": "billing"}
    )

    assert passed is True
    assert actual == '{"category": "billing"}'


def test_a_dotted_field_reads_into_nested_output():
    passed, actual = judge(
        _expect("equals", field="structured.amount", value="42"),
        {"structured": {"amount": 42}},
    )

    assert passed is True
    assert actual == "42"


def test_a_missing_path_reads_as_empty_so_not_contains_passes():
    passed, actual = judge(_expect("not_contains"), {"other": "billing"})

    assert passed is True
    assert actual == ""


def test_a_non_dict_on_the_path_reads_as_empty():
    passed, actual = judge(_expect("contains", field="text.word"), {"text": "billing"})

    assert passed is False
    assert actual == ""


def test_a_long_answer_is_clipped_to_what_a_result_shows():
    long_text = "x" * 600

    _, actual = judge(_expect("contains", value="x"), {"text": long_text})

    assert actual == "x" * 500


@pytest.mark.parametrize("kind", ["contains", "not_contains", "equals"])
def test_each_kind_accepts_the_same_shape(kind: str):
    expectation = _expect(kind)

    assert expectation.kind == kind


def test_an_unknown_kind_is_rejected():
    with pytest.raises(ValidationError):
        EvalExpectation(kind="sounds_like", value="billing")  # type: ignore[arg-type]


def test_an_empty_value_is_rejected():
    with pytest.raises(ValidationError):
        EvalExpectation(value="")


def test_a_field_that_is_not_a_path_is_rejected():
    with pytest.raises(ValidationError):
        EvalExpectation(field="text..amount", value="42")
