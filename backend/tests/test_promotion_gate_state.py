"""Where one guard stands on a version: only a current pass lets it through."""

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
_SCORING = "scoring-now"


def _suite(*, active: bool = True, pinned: bool = True) -> EvalSuite:
    return EvalSuite(
        id=uuid.uuid4(),
        dataset_id=_DATASET,
        is_active=active,
        min_pass_rate=Decimal("0.9"),
        max_confirmed_regressions=0,
        pinned_dataset_version=3 if pinned else None,
        pinned_scoring={} if pinned else None,
    )


def _result(suite: EvalSuite, status: str) -> EvalSuiteResult:
    return EvalSuiteResult(
        id=uuid.uuid4(),
        suite_id=suite.id,
        status=status,
        dataset_id=_DATASET,
        threshold=threshold_of(suite).model_dump(mode="json"),
    )


def _state(
    suite: EvalSuite,
    settled: tuple[EvalSuiteResult, int | None, str | None] | None,
    waiting: EvalSuiteResult | None = None,
):
    return guard_state(
        suite,
        None if settled is None else (*settled, None, True),
        waiting,
        dataset_version=3,
        scoring_hash=_SCORING,
    )


def test_a_pass_over_the_dataset_and_scoring_the_suite_holds_now_passes() -> None:
    suite = _suite()
    passed = _result(suite, "passed")
    assert _state(suite, (passed, 3, _SCORING)) == ("passed", passed)


@pytest.mark.parametrize("status", ["failed", "inconclusive", "skipped", "error"])
def test_any_other_current_result_holds_the_version_back_as_itself(status: str) -> None:
    suite = _suite()
    result = _result(suite, status)
    ran = (None, None) if status in ("skipped", "error") else (3, _SCORING)
    assert _state(suite, (result, *ran)) == (status, result)


def test_a_pass_over_an_older_dataset_version_is_stale() -> None:
    suite = _suite()
    passed = _result(suite, "passed")
    assert _state(suite, (passed, 2, _SCORING)) == ("stale", passed)


def test_a_pass_graded_under_other_scoring_is_stale() -> None:
    """A judge switched off for one run and back on does not leave that run's pass behind."""
    suite = _suite()
    passed = _result(suite, "passed")
    assert _state(suite, (passed, 3, "scoring-then")) == ("stale", passed)


def test_a_pass_whose_eval_run_is_gone_is_stale() -> None:
    suite = _suite()
    passed = _result(suite, "passed")
    assert _state(suite, (passed, None, None)) == ("stale", passed)


def test_a_result_under_another_threshold_or_dataset_is_stale() -> None:
    suite = _suite()
    raised = _result(suite, "failed")
    raised.threshold = {**raised.threshold, "min_pass_rate": 0.5}
    moved = _result(suite, "failed")
    moved.dataset_id = uuid.uuid4()
    assert _state(suite, (raised, 3, _SCORING))[0] == "stale"
    assert _state(suite, (moved, 3, _SCORING))[0] == "stale"


def test_a_run_going_on_the_version_is_checking_unless_it_already_passed() -> None:
    suite = _suite()
    waiting = _result(suite, "running")
    passed = _result(suite, "passed")
    failed = _result(suite, "failed")
    assert _state(suite, None, waiting) == ("checking", waiting)
    assert _state(suite, (failed, 3, _SCORING), waiting) == ("checking", waiting)
    assert _state(suite, (passed, 3, _SCORING), waiting) == ("passed", passed)


def test_no_result_is_unchecked() -> None:
    assert _state(_suite(), None) == ("unchecked", None)


def test_a_paused_guard_holds_the_version_back_whatever_it_found() -> None:
    """A run that passes after the pause does not promote past it."""
    paused = _suite(active=False)
    passed = _result(paused, "passed")
    running = _result(paused, "running")
    assert _state(paused, None) == ("paused", None)
    assert _state(paused, (passed, 3, _SCORING)) == ("paused", passed)
    assert _state(paused, None, running) == ("paused", running)


def test_a_guard_not_pinned_yet_holds_the_version_back_whatever_it_found() -> None:
    """Pinned to nothing it would read whatever its dataset turned into."""
    unpinned = _suite(pinned=False)
    passed = _result(unpinned, "passed")
    running = _result(unpinned, "running")
    assert _state(unpinned, None) == ("unpinned", None)
    assert _state(unpinned, (passed, 3, _SCORING)) == ("unpinned", passed)
    assert _state(unpinned, None, running) == ("unpinned", running)


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
    version = uuid.uuid4()

    assert (
        await eval_suite_repo.settled_on_version(
            db, [], version, baseline_version=1, organization_id=org
        )
        == {}
    )
    assert (
        await eval_suite_repo.open_on_version(
            db, [], version, baseline_version=1, organization_id=org
        )
        == {}
    )
    assert await promotion_gate_repo.guards_for(db, [], organization_id=org) == {}
    assert await promotion_gate_repo.guarding(db, [], organization_id=org) == set()
    assert await promotion_gate_repo.overrides_for_versions(db, [], organization_id=org) == {}
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("pinned,version", [(True, uuid.uuid4()), (False, None)])
def test_a_pass_from_another_or_unpinned_judge_cannot_open_the_gate(
    pinned: bool, version: uuid.UUID | None
) -> None:
    suite = _suite()
    passed = _result(suite, "passed")
    assert guard_state(
        suite,
        (passed, 3, _SCORING, version, pinned),
        None,
        dataset_version=3,
        scoring_hash=_SCORING,
    ) == ("stale", passed)
