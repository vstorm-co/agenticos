"""A suite's threshold: quality decides, efficiency only when asked, and an invalid
comparison decides nothing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.db.models.eval_run import ArmRole, ArmSource
from app.db.models.eval_suite import EvalSuiteResultStatus
from app.schemas.eval_run import ArmSummaryRead, ComparisonSide, EvalComparisonRead
from app.schemas.eval_suite import EvalSuiteSchedule, EvalSuiteThreshold
from app.services.eval_suite import fires_per_month
from app.services.eval_suite_threshold import judge, rise


def _summary(**values: Any) -> ArmSummaryRead:
    base: dict[str, Any] = {
        "cases": 10,
        "passed": 10,
        "failed": 0,
        "incomplete": 0,
        "pass_rate": 1.0,
        "first_pass_rate": 1.0,
        "cost_usd": Decimal("1.00"),
        "cost_per_pass_usd": Decimal("0.10"),
        "avg_tokens": 100.0,
        "p50_ms": 400.0,
        "p95_ms": 1000.0,
    }
    return ArmSummaryRead(**{**base, **values})


def _side() -> ComparisonSide:
    return ComparisonSide(
        run_id=uuid.uuid4(),
        arm_id=uuid.uuid4(),
        role=ArmRole.CANDIDATE,
        source=ArmSource.VERSION,
        version_number=7,
        model_label="gpt-test",
        dataset_version=1,
        finished_at=datetime.now(UTC),
    )


def _comparison(
    *, baseline: bool = True, candidate: ArmSummaryRead | None = None, **values: Any
) -> EvalComparisonRead:
    base: dict[str, Any] = {
        "candidate": _side(),
        "baseline": _side() if baseline else None,
        "paired": baseline,
        "verdict": "no_difference" if baseline else None,
        "overall": None,
        "p_value": None,
        "invalid_reason": None,
        "regressions_confirmed": 0,
        "regressions_unconfirmed": 0,
        "fixed_confirmed": 0,
        "fixed_unconfirmed": 0,
        "compared": 10 if baseline else 0,
        "not_compared": 0,
        "candidate_summary": candidate or _summary(),
        "baseline_summary": _summary() if baseline else None,
        "efficiency": None,
        "cases": [],
        "flips_by_tag": {},
    }
    return EvalComparisonRead(**{**base, **values})


def test_a_run_meeting_every_limit_passes() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(min_pass_rate=0.8), _summary(pass_rate=0.9), _comparison()
    )
    assert (status, reasons) == (EvalSuiteResultStatus.PASSED, [])


def test_one_confirmed_regression_fails_by_default() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(), _summary(), _comparison(verdict="worse", regressions_confirmed=1)
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [(r.code, r.value, r.limit) for r in reasons] == [("regressions", 1, 0)]


def test_an_owner_may_allow_some_regressions() -> None:
    status, _ = judge(
        EvalSuiteThreshold(max_confirmed_regressions=2),
        _summary(),
        _comparison(verdict="worse", regressions_confirmed=2),
    )
    assert status is EvalSuiteResultStatus.PASSED


def test_unconfirmed_flips_and_the_mcnemar_direction_decide_nothing() -> None:
    status, _ = judge(
        EvalSuiteThreshold(),
        _summary(),
        _comparison(regressions_unconfirmed=4, overall="worse", p_value=0.01),
    )
    assert status is EvalSuiteResultStatus.PASSED


def test_a_pass_rate_below_the_minimum_fails() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(min_pass_rate=0.8), _summary(pass_rate=0.5), _comparison()
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [(r.code, r.value, r.limit) for r in reasons] == [("pass_rate_below", 0.5, 0.8)]


def test_nothing_graded_against_a_minimum_fails() -> None:
    _, reasons = judge(
        EvalSuiteThreshold(min_pass_rate=0.8), _summary(pass_rate=None), _comparison()
    )
    assert [r.code for r in reasons] == ["nothing_graded"]


def test_without_a_baseline_only_the_pass_rate_is_held() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(max_cost_per_pass_rise=0.1),
        _summary(),
        _comparison(baseline=False, regressions_confirmed=3),
    )
    assert (status, reasons) == (EvalSuiteResultStatus.PASSED, [])


def test_an_invalid_comparison_is_inconclusive_never_a_pass() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(),
        _summary(),
        _comparison(verdict="invalid", invalid_reason="A different judge graded the baseline"),
    )
    assert status is EvalSuiteResultStatus.INCONCLUSIVE
    assert reasons[0].detail == "A different judge graded the baseline"


def test_efficiency_is_held_only_where_a_ceiling_was_set() -> None:
    dearer = _summary(cost_per_pass_usd=Decimal("0.20"), p95_ms=3000.0)

    unset, _ = judge(EvalSuiteThreshold(), _summary(), _comparison(candidate=dearer))
    status, reasons = judge(
        EvalSuiteThreshold(max_cost_per_pass_rise=0.5, max_p95_rise=1.0),
        _summary(),
        _comparison(candidate=dearer),
    )

    assert unset is EvalSuiteResultStatus.PASSED
    assert status is EvalSuiteResultStatus.FAILED
    assert [(r.code, r.value) for r in reasons] == [("cost_per_pass_rise", 1.0), ("p95_rise", 2.0)]


def test_a_rise_needs_both_sides_and_a_positive_baseline() -> None:
    assert rise(Decimal("0.3"), Decimal("0.2")) == pytest.approx(0.5)
    assert rise(None, Decimal("0.2")) is None
    assert rise(Decimal("0.3"), None) is None
    assert rise(Decimal("0.3"), Decimal("0")) is None


def test_a_schedule_must_fire_in_a_known_zone() -> None:
    assert EvalSuiteSchedule(cron="0 6 * * *", timezone="Europe/Warsaw").timezone == "Europe/Warsaw"
    with pytest.raises(ValidationError, match="five-field"):
        EvalSuiteSchedule(cron="0 0 31 2 *")
    with pytest.raises(ValidationError, match="IANA"):
        EvalSuiteSchedule(cron="0 6 * * *", timezone="Mars/Olympus")


def test_a_month_of_a_daily_schedule_is_thirty_runs() -> None:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    assert fires_per_month(EvalSuiteSchedule(cron="0 6 * * *"), now=now) == 30
    # A Monday noon: the next four Mondays fall inside the thirty days.
    assert fires_per_month(EvalSuiteSchedule(cron="0 6 * * 1"), now=now) == 4
