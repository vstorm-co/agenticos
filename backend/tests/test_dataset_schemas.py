"""What a case refuses before it reaches the service, and how its rows print."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.db.models.dataset import Dataset, DatasetCase, DatasetVersion, DatasetVersionCase
from app.schemas.dataset import DatasetCaseCreate, DatasetCaseUpdate


def test_a_regex_check_must_compile() -> None:
    with pytest.raises(ValidationError, match="Not a valid regular expression"):
        DatasetCaseCreate(input="q", checks=[{"type": "regex", "value": "("}])
    assert DatasetCaseCreate(input="q", checks=[{"type": "contains", "value": "("}]).checks


def test_tags_are_trimmed_and_deduplicated_in_order() -> None:
    assert DatasetCaseCreate(input="q", tags=[" b", "a", "b ", " "]).tags == ["b", "a"]


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


def test_an_edit_that_leaves_the_tags_alone_does_not_clear_them() -> None:
    assert DatasetCaseUpdate(note="n").tags is None
    assert DatasetCaseUpdate(tags=[" a "]).tags == ["a"]


def test_every_row_says_which_dataset_it_belongs_to() -> None:
    dataset_id = uuid.uuid4()
    rows = [
        Dataset(name="refunds", latest_version=3),
        DatasetVersion(dataset_id=dataset_id, number=2),
        DatasetCase(dataset_id=dataset_id, case_id=uuid.uuid4()),
        DatasetVersionCase(version_id=uuid.uuid4(), position=4),
    ]
    printed = [repr(row) for row in rows]
    assert "refunds" in printed[0]
    assert str(dataset_id) in printed[1]
    assert str(dataset_id) in printed[2]
    assert "at=4" in printed[3]
