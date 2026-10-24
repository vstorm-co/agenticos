"""A suite's threshold: quality decides, efficiency only when asked, and an invalid
comparison decides nothing."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.db.models.eval_run import ArmRole, ArmSource
from app.db.models.eval_suite import EvalSuiteResultStatus
from app.schemas.eval_run import ArmSummaryRead, ComparisonSide, EvalComparisonRead
from app.schemas.eval_suite import EvalSuiteResultRead, EvalSuiteSchedule, EvalSuiteThreshold
from app.services.eval_suite import fires_per_month
from app.services.eval_suite_threshold import judge, rise


def _summary(**values: Any) -> ArmSummaryRead:
    base: dict[str, Any] = {
        "cases": 10,
        "passed": 10,
        "failed": 0,
        "incomplete": 0,
        "ungraded": 0,
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
        EvalSuiteThreshold(),
        _summary(),
        _comparison(verdict="worse", regressions_confirmed=1),
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
        EvalSuiteThreshold(min_pass_rate=0.8),
        _summary(passed=5, failed=5, pass_rate=0.5),
        _comparison(),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [(r.code, r.value, r.limit) for r in reasons] == [("pass_rate_below", 0.5, 0.8)]


@pytest.mark.parametrize("minimum", [None, 0.8])
def test_a_run_in_which_nothing_was_graded_is_inconclusive(minimum: float | None) -> None:
    """The judge erred on every case: a result that checked nothing passes nothing."""
    status, reasons = judge(
        EvalSuiteThreshold(min_pass_rate=minimum),
        _summary(pass_rate=None),
        _comparison(),
    )
    assert status is EvalSuiteResultStatus.INCONCLUSIVE
    assert [(r.code, r.limit) for r in reasons] == [("nothing_graded", minimum)]


def test_without_a_baseline_only_the_pass_rate_is_held() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(min_pass_rate=0.8, max_cost_per_pass_rise=0.1),
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


def test_a_pass_rate_below_the_minimum_fails_even_when_the_baseline_cannot_be_compared() -> None:
    """The minimum is the candidate's own number; an incomparable baseline does not excuse it."""
    status, reasons = judge(
        EvalSuiteThreshold(min_pass_rate=0.8),
        _summary(passed=5, failed=5, pass_rate=0.5),
        _comparison(verdict="invalid", invalid_reason="A different judge graded the baseline"),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [r.code for r in reasons] == ["pass_rate_below"]


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


def test_a_ceiling_crossed_while_a_case_is_undecided_waits_for_it() -> None:
    """An open case that passes later changes cost per passed case."""
    dearer = _summary(cost_per_pass_usd=Decimal("0.20"))
    status, reasons = judge(
        EvalSuiteThreshold(max_cost_per_pass_rise=0.5),
        _summary(passed=9, incomplete=1, pass_rate=1.0),
        _comparison(candidate=dearer),
    )
    assert status is EvalSuiteResultStatus.INCONCLUSIVE
    assert [r.code for r in reasons] == ["incomplete", "cost_per_pass_rise"]


def test_a_rise_needs_both_sides_and_handles_a_free_baseline() -> None:
    assert rise(Decimal("0.3"), Decimal("0.2")) == pytest.approx(0.5)
    assert rise(None, Decimal("0.2")) is None
    assert rise(Decimal("0.3"), None) is None
    assert rise(Decimal("0.3"), Decimal("0")) == float("inf")
    assert rise(Decimal("0"), Decimal("0")) == 0


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


def test_a_case_nobody_graded_keeps_the_result_from_passing() -> None:
    """One passing case and one nothing grades: the pass rate is 100% of what was decided."""
    status, reasons = judge(
        EvalSuiteThreshold(min_pass_rate=0.9),
        _summary(cases=2, passed=1, ungraded=1, pass_rate=1.0),
        _comparison(),
    )
    assert status is EvalSuiteResultStatus.INCONCLUSIVE
    assert [(r.code, r.value) for r in reasons] == [("ungraded", 1)]


def test_a_case_the_provider_or_a_scorer_failed_on_keeps_the_result_from_passing() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(), _summary(passed=9, incomplete=1, pass_rate=1.0), _comparison()
    )
    assert status is EvalSuiteResultStatus.INCONCLUSIVE
    assert [(r.code, r.value) for r in reasons] == [("incomplete", 1)]


@pytest.mark.parametrize(("passed", "crashed"), [(0, 15), (1, 14)])
def test_an_agent_that_crashed_fails_with_no_minimum_and_no_baseline(
    passed: int, crashed: int
) -> None:
    """A first result with the threshold left empty still fails on a crash."""
    status, reasons = judge(
        EvalSuiteThreshold(),
        _summary(
            cases=15,
            passed=passed,
            failed=crashed,
            crashed=crashed,
            pass_rate=passed / 15,
        ),
        _comparison(baseline=False),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [(r.code, r.value) for r in reasons] == [("crashed", crashed)]


def test_a_crash_whose_reruns_tied_still_fails_with_nothing_else_decided() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(),
        _summary(cases=1, passed=0, incomplete=1, crashed=1, pass_rate=None),
        _comparison(),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [(r.code, r.value) for r in reasons] == [("crashed", 1)]


def test_a_crash_fails_even_when_the_comparison_is_invalid() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(),
        _summary(passed=9, failed=1, crashed=1, pass_rate=0.9),
        _comparison(verdict="invalid", invalid_reason="A different judge graded the baseline"),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [r.code for r in reasons] == ["crashed"]


def test_a_crash_on_both_sides_fails_though_nothing_flipped() -> None:
    crashed = _summary(cases=10, passed=0, failed=10, crashed=10, pass_rate=0.0)
    status, reasons = judge(
        EvalSuiteThreshold(),
        crashed,
        _comparison(verdict="no_difference", candidate=crashed),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [r.code for r in reasons] == ["crashed"]


def test_a_crash_fails_whatever_is_left_undecided() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(),
        _summary(passed=7, failed=1, crashed=1, ungraded=2, pass_rate=7 / 8),
        _comparison(),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [r.code for r in reasons] == ["crashed"]


def test_an_agent_that_crashed_on_most_cases_fails() -> None:
    """Fourteen crashes are fourteen failures: the pass rate is one in fifteen."""
    status, reasons = judge(
        EvalSuiteThreshold(min_pass_rate=0.9),
        _summary(cases=15, passed=1, failed=14, crashed=14, pass_rate=1 / 15),
        _comparison(),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [(r.code, r.value, r.limit) for r in reasons] == [
        ("pass_rate_below", pytest.approx(0.0667, abs=1e-4), 0.9),
        ("crashed", 14, None),
    ]


def test_a_minimum_the_undecided_cases_could_still_reach_is_inconclusive() -> None:
    """One failure and three undecided: were all three to pass, the rate is 75%."""
    status, reasons = judge(
        EvalSuiteThreshold(min_pass_rate=0.5),
        _summary(cases=4, passed=0, failed=1, incomplete=1, ungraded=2, pass_rate=0.0),
        _comparison(),
    )
    assert status is EvalSuiteResultStatus.INCONCLUSIVE
    assert [r.code for r in reasons] == ["pass_rate_below", "incomplete", "ungraded"]


def test_a_minimum_out_of_reach_whatever_the_undecided_cases_do_fails() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(min_pass_rate=0.9),
        _summary(cases=4, passed=1, failed=2, ungraded=1, pass_rate=1 / 3),
        _comparison(),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [r.code for r in reasons] == ["pass_rate_below"]


def test_an_invalid_comparison_names_the_undecided_cases_too() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(),
        _summary(passed=9, ungraded=1, pass_rate=1.0),
        _comparison(verdict="invalid", invalid_reason="A different judge graded the baseline"),
    )
    assert status is EvalSuiteResultStatus.INCONCLUSIVE
    assert [r.code for r in reasons] == ["invalid_comparison", "ungraded"]


def test_a_confirmed_regression_fails_whatever_else_went_ungraded() -> None:
    status, reasons = judge(
        EvalSuiteThreshold(),
        _summary(passed=6, incomplete=1, ungraded=3, pass_rate=1.0),
        _comparison(verdict="worse", regressions_confirmed=1),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert [r.code for r in reasons] == ["regressions"]


@pytest.mark.parametrize("status", list(EvalSuiteResultStatus))
def test_a_result_says_whether_it_alerts_as_its_status_does(status: EvalSuiteResultStatus) -> None:
    """The dashboard reads `alerting` off the result rather than keeping its own list."""
    read = EvalSuiteResultRead.model_construct(status=status)

    assert read.alerting is status.alerting
    assert "alerting" in EvalSuiteResultRead.model_json_schema(mode="serialization")["properties"]


@pytest.mark.parametrize("rate", [0.0, 0.5, 1.0])
def test_a_first_measurement_without_a_minimum_sets_a_baseline_not_a_pass(rate: float) -> None:
    status, reasons = judge(
        EvalSuiteThreshold(), _summary(pass_rate=rate), _comparison(baseline=False)
    )
    assert (status, reasons) == (EvalSuiteResultStatus.BASELINE_SET, [])


@pytest.mark.parametrize("ceiling", [0, 0.2, 100])
def test_paid_candidate_against_free_baseline_exceeds_every_ceiling(ceiling: float) -> None:
    status, reasons = judge(
        EvalSuiteThreshold(max_cost_per_pass_rise=ceiling),
        _summary(),
        _comparison(baseline_summary=_summary(cost_per_pass_usd=Decimal(0))),
    )
    assert status is EvalSuiteResultStatus.FAILED
    assert reasons[0].code == "cost_per_pass_rise"
    assert reasons[0].detail == "zero_baseline"
    assert reasons[0].value is None
    assert "Infinity" not in reasons[0].model_dump_json()
