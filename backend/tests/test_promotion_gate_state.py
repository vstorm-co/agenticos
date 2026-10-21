"""Where one guard stands on a version: only a current pass lets it through."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.db.models.eval_suite import EvalSuite, EvalSuiteResult
from app.db.models.promotion_gate import EnvironmentGuard, PromotionOverride
from app.repositories import eval_suite_repo, promotion_gate_repo
from app.services.eval_suite import threshold_of
from app.services.promotion_gate import guard_state

_DATASET = uuid.uuid4()


def _suite(*, active: bool = True) -> EvalSuite:
    return EvalSuite(
        id=uuid.uuid4(),
        dataset_id=_DATASET,
        is_active=active,
        min_pass_rate=Decimal("0.9"),
        max_confirmed_regressions=0,
    )


def _result(suite: EvalSuite, status: str, **values: object) -> EvalSuiteResult:
    return EvalSuiteResult(
        id=uuid.uuid4(),
        suite_id=suite.id,
        status=status,
        dataset_id=_DATASET,
        threshold=threshold_of(suite).model_dump(mode="json"),
        **values,
    )


def test_a_pass_over_the_dataset_version_the_suite_reads_now_passes() -> None:
    suite = _suite()
    passed = _result(suite, "passed")
    assert guard_state(suite, (passed, 3), None, dataset_version=3) == ("passed", passed)


@pytest.mark.parametrize("status", ["failed", "inconclusive", "skipped", "error"])
def test_any_other_current_result_holds_the_version_back_as_itself(status: str) -> None:
    suite = _suite()
    result = _result(suite, status)
    number = None if status in ("skipped", "error") else 3
    assert guard_state(suite, (result, number), None, dataset_version=3) == (status, result)


def test_a_pass_over_an_older_dataset_version_is_stale() -> None:
    suite = _suite()
    passed = _result(suite, "passed")
    assert guard_state(suite, (passed, 2), None, dataset_version=3) == ("stale", passed)


def test_a_pass_whose_eval_run_is_gone_is_stale() -> None:
    suite = _suite()
    passed = _result(suite, "passed")
    assert guard_state(suite, (passed, None), None, dataset_version=3) == ("stale", passed)


def test_a_result_under_another_threshold_or_dataset_is_stale() -> None:
    suite = _suite()
    raised = _result(suite, "failed")
    raised.threshold = {**raised.threshold, "min_pass_rate": 0.5}
    moved = _result(suite, "failed")
    moved.dataset_id = uuid.uuid4()
    assert guard_state(suite, (raised, 3), None, dataset_version=3)[0] == "stale"
    assert guard_state(suite, (moved, 3), None, dataset_version=3)[0] == "stale"


def test_a_run_going_on_the_version_is_checking_unless_it_already_passed() -> None:
    suite = _suite()
    waiting = _result(suite, "running")
    passed = _result(suite, "passed")
    failed = _result(suite, "failed")
    assert guard_state(suite, None, waiting, dataset_version=3) == ("checking", waiting)
    assert guard_state(suite, (failed, 3), waiting, dataset_version=3) == ("checking", waiting)
    assert guard_state(suite, (passed, 3), waiting, dataset_version=3) == ("passed", passed)


def test_no_result_is_unchecked_or_paused_when_nothing_will_produce_one() -> None:
    assert guard_state(_suite(), None, None, dataset_version=3) == ("unchecked", None)
    assert guard_state(_suite(active=False), None, None, dataset_version=3) == ("paused", None)
    paused = _suite(active=False)
    old = _result(paused, "passed")
    assert guard_state(paused, (old, 2), None, dataset_version=3) == ("paused", old)


def test_rows_say_what_they_are() -> None:
    suite = uuid.uuid4()
    guard = EnvironmentGuard(environment_id=uuid.uuid4(), suite_id=suite)
    override = PromotionOverride(id=uuid.uuid4(), environment_name="production")

    assert str(suite) in repr(guard)
    assert "production" in repr(override)


@pytest.mark.anyio
async def test_asking_about_nothing_reads_nothing() -> None:
    db = AsyncMock()
    org = uuid.uuid4()

    assert await eval_suite_repo.settled_on_version(db, [], uuid.uuid4(), organization_id=org) == {}
    assert await eval_suite_repo.open_on_version(db, [], uuid.uuid4(), organization_id=org) == {}
    assert await promotion_gate_repo.guards_for(db, [], organization_id=org) == {}
    assert await promotion_gate_repo.overrides_for_versions(db, [], organization_id=org) == {}
    db.execute.assert_not_awaited()
