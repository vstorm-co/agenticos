"""What a case refuses before it reaches the service, and how its rows print."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.db.models.dataset import Dataset, DatasetCase, DatasetVersion
from app.schemas.dataset import (
    NO_EXPECTATION,
    DatasetCaseCreate,
    DatasetCaseRead,
    DatasetCaseUpdate,
)


def test_a_check_needs_a_type_and_json_parameters() -> None:
    with pytest.raises(ValidationError, match="type"):
        DatasetCaseCreate(input="q", checks=[{"value": "x"}])
    with pytest.raises(ValidationError):
        DatasetCaseCreate(input="q", checks=[{"type": "contains", "value": object()}])
    case = DatasetCaseCreate(input="q", checks=[{"type": "contains", "value": "("}])
    assert case.checks[0].model_dump() == {"type": "contains", "value": "("}


def test_an_order_mode_is_one_of_three() -> None:
    assert DatasetCaseCreate(input="q", reference_answer="a").order_mode == "any"
    with pytest.raises(ValidationError):
        DatasetCaseCreate(input="q", reference_answer="a", order_mode="sorted")


def test_tags_are_trimmed_and_deduplicated_in_order() -> None:
    assert DatasetCaseCreate(
        input="q", note="n", counter_example="c", tags=[" b", "a", "b ", " "]
    ).tags == ["b", "a"]


@pytest.mark.parametrize(
    ("tags", "reason"),
    [
        (["a,b"], "comma"),
        (["x" * 65], "64 characters"),
        ([f"t{n}" for n in range(21)], "at most 20"),
    ],
)
def test_a_tag_a_csv_could_not_carry_is_refused(tags: list[str], reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        DatasetCaseCreate(input="q", tags=tags)


@pytest.mark.parametrize(
    "expectation",
    [
        {"reference_answer": "a"},
        {"counter_example": "c"},
        {"expected_tool_calls": [{"tool": "search"}]},
        {"checks": [{"type": "contains", "value": "x"}]},
    ],
)
def test_any_one_expectation_makes_a_case(expectation: dict[str, object]) -> None:
    assert DatasetCaseCreate.model_validate({"input": "q", **expectation}).input == "q"


def test_a_case_with_only_an_input_is_refused_against_the_reference_answer() -> None:
    with pytest.raises(ValidationError) as refused:
        DatasetCaseCreate(input="q", reference_answer="", tags=["a"], note="why")
    [error] = refused.value.errors()
    assert error["loc"] == ("reference_answer",)
    assert error["msg"] == NO_EXPECTATION


def test_a_stored_case_with_only_an_input_still_reads() -> None:
    row = DatasetCase(
        id=uuid.uuid4(),
        case_id=uuid.uuid4(),
        input="q",
        history=[],
        expected_tool_calls=[],
        order_mode="any",
        checks=[],
        tags=[],
        source="manual",
        created_at=datetime.now(UTC),
    )
    assert DatasetCaseRead.model_validate(row).input == "q"


def test_an_edit_that_leaves_the_tags_alone_does_not_clear_them() -> None:
    assert DatasetCaseUpdate(note="n").tags is None
    assert DatasetCaseUpdate(tags=[" a "]).tags == ["a"]


def test_every_row_says_which_dataset_it_belongs_to() -> None:
    dataset_id = uuid.uuid4()
    rows = [
        Dataset(name="refunds", latest_version=3),
        DatasetVersion(dataset_id=dataset_id, number=2),
        DatasetCase(dataset_id=dataset_id, case_id=uuid.uuid4()),
    ]
    printed = [repr(row) for row in rows]
    assert "refunds" in printed[0]
    assert str(dataset_id) in printed[1]
    assert str(dataset_id) in printed[2]
