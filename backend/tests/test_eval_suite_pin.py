"""Which threshold changes loosen a guard, and what a guard reads."""

import uuid

import pytest

from app.db.models.dataset import Dataset
from app.db.models.eval_suite import EvalSuite
from app.schemas.eval_suite import EvalSuiteThreshold
from app.schemas.scoring import DatasetScoring
from app.services.eval_suite import loosens, pin_of, reads_now

_WAS = EvalSuiteThreshold(
    min_pass_rate=0.8, max_confirmed_regressions=2, max_cost_per_pass_rise=0.5, max_p95_rise=0.3
)


def _now(**values: object) -> EvalSuiteThreshold:
    return _WAS.model_copy(update=values)


@pytest.mark.parametrize(
    "values",
    [
        {"min_pass_rate": 0.9},
        {"max_confirmed_regressions": 0},
        {"max_cost_per_pass_rise": 0.1},
        {"max_p95_rise": 0.0},
        {"min_pass_rate": 0.95, "max_confirmed_regressions": 1},
        {},
    ],
)
def test_a_stricter_or_equal_bar_does_not_loosen(values: dict[str, object]) -> None:
    assert not loosens(_WAS, _now(**values))


@pytest.mark.parametrize(
    "values",
    [
        {"min_pass_rate": 0.5},
        {"min_pass_rate": None},
        {"max_confirmed_regressions": 3},
        {"max_cost_per_pass_rise": 0.6},
        {"max_cost_per_pass_rise": None},
        {"max_p95_rise": None},
        {"min_pass_rate": 0.95, "max_confirmed_regressions": 3},
    ],
)
def test_a_lower_bar_or_one_taken_away_loosens(values: dict[str, object]) -> None:
    assert loosens(_WAS, _now(**values))


def test_a_bar_set_where_there_was_none_tightens() -> None:
    assert not loosens(
        EvalSuiteThreshold(),
        EvalSuiteThreshold(min_pass_rate=0.5, max_cost_per_pass_rise=1.0, max_p95_rise=1.0),
    )


def test_a_pinned_suite_reads_its_pin_and_an_unpinned_one_the_latest() -> None:
    pinned_scoring = DatasetScoring().model_dump(mode="json")
    latest_scoring = {**pinned_scoring, "trajectory": {"enabled": False, "required": False}}
    dataset = Dataset(id=uuid.uuid4(), latest_version=9, scoring=latest_scoring)
    pinned = EvalSuite(
        dataset_id=dataset.id, pinned_dataset_version=7, pinned_scoring=pinned_scoring
    )
    following = EvalSuite(dataset_id=dataset.id)

    assert reads_now(pinned, dataset) == (7, DatasetScoring.model_validate(pinned_scoring))
    assert reads_now(following, dataset) == (9, DatasetScoring.model_validate(latest_scoring))
    assert pin_of(following) is None
