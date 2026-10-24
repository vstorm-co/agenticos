"""The arithmetic behind an eval comparison: flips, confirmation, verdicts and axes."""

import uuid
from decimal import Decimal

import pytest

from app.services.eval_comparison import (
    Attempt,
    Flip,
    PairedCase,
    QualityVerdict,
    Trend,
    Verdict,
    classify,
    efficiency,
    flips_by_tag,
    mcnemar_p,
    percentile,
    quality_verdict,
    settle,
    summarize,
    trend,
)


def _case(
    baseline,
    candidate,
    *,
    baseline_reruns=(),
    candidate_reruns=(),
    tags=(),
) -> PairedCase:
    return PairedCase(
        case_id=uuid.uuid4(),
        baseline=baseline,
        candidate=candidate,
        baseline_reruns=tuple(baseline_reruns),
        candidate_reruns=tuple(candidate_reruns),
        tags=tuple(tags),
    )


class TestClassify:
    @pytest.mark.parametrize(
        ("baseline", "candidate", "flip"),
        [
            (True, False, Flip.REGRESSION),
            (False, True, Flip.FIXED),
            (True, True, Flip.UNCHANGED),
            (False, False, Flip.UNCHANGED),
            (None, True, Flip.INCOMPLETE),
            (True, None, Flip.INCOMPLETE),
        ],
    )
    def test_each_pair_of_outcomes_has_one_flip(self, baseline, candidate, flip):
        assert classify(baseline, candidate) is flip

    def test_an_incomplete_case_is_never_a_regression(self):
        """A judge that could not run says nothing about the candidate."""
        assert _case(True, None).flip is Flip.INCOMPLETE


class TestConfirmation:
    def test_a_regression_every_rerun_repeats_is_confirmed(self):
        case = _case(True, False, baseline_reruns=[True, True], candidate_reruns=[False, False])
        assert case.confirmed

    def test_a_baseline_nobody_reran_confirms_nothing(self):
        """One lucky pass of the baseline against three failures is no regression."""
        assert not _case(True, False, candidate_reruns=[False, False]).confirmed

    def test_failed_failed_passed_against_three_passes_holds_no_change(self):
        assert not _case(
            True, False, baseline_reruns=[True, True], candidate_reruns=[False, True]
        ).confirmed

    def test_one_rerun_that_passes_leaves_it_unconfirmed(self):
        """A flaky case is reported, not counted against the candidate."""
        assert not _case(True, False, candidate_reruns=[False, True]).confirmed

    def test_a_paired_baseline_must_repeat_its_pass_too(self):
        """If the baseline also fails on a rerun, the provider moved, not the spec."""
        case = _case(True, False, baseline_reruns=[True, False], candidate_reruns=[False, False])
        assert not case.confirmed

    def test_a_flip_nobody_reran_is_unconfirmed(self):
        assert not _case(True, False).confirmed

    def test_an_unchanged_case_is_never_confirmed(self):
        assert not _case(True, True, candidate_reruns=[True, True]).confirmed

    def test_a_fix_is_confirmed_the_same_way(self):
        assert _case(False, True, baseline_reruns=[False], candidate_reruns=[True, True]).confirmed


class TestMcNemar:
    def test_no_flips_is_no_evidence(self):
        assert mcnemar_p(0, 0) == 1.0

    def test_a_balanced_split_is_no_evidence(self):
        assert mcnemar_p(3, 3) == 1.0

    def test_eight_regressions_and_no_fix_is_significant(self):
        assert mcnemar_p(8, 0) == pytest.approx(2 / 2**8)

    def test_the_test_is_symmetric(self):
        assert mcnemar_p(2, 9) == mcnemar_p(9, 2)


def _broke():
    return _case(True, False, baseline_reruns=[True, True], candidate_reruns=[False, False])


def _fixed():
    return _case(False, True, baseline_reruns=[False, False], candidate_reruns=[True, True])


class TestQualityVerdict:
    def test_one_confirmed_regression_makes_it_worse_without_an_overall(self):
        """A case that breaks every time is reason enough not to publish, though
        one flip says nothing about the candidate as a whole."""
        cases = [_broke()] + [_case(True, True) for _ in range(19)]
        assert quality_verdict(cases, alpha=0.05) == QualityVerdict(Verdict.WORSE, 1.0, None)

    def test_many_confirmed_regressions_make_it_worse_overall(self):
        quality = quality_verdict([_broke() for _ in range(8)], alpha=0.05)
        assert (quality.verdict, quality.overall) == (Verdict.WORSE, "worse")
        assert quality.p_value is not None and quality.p_value < 0.05

    def test_confirmed_fixes_alone_make_it_better(self):
        assert quality_verdict([_fixed()], alpha=0.05).verdict is Verdict.BETTER
        quality = quality_verdict([_fixed() for _ in range(8)], alpha=0.05)
        assert (quality.verdict, quality.overall) == (Verdict.BETTER, "better")

    def test_a_regression_beside_fixes_is_mixed(self):
        quality = quality_verdict([_broke()] + [_fixed() for _ in range(9)], alpha=0.05)
        assert (quality.verdict, quality.overall) == (Verdict.MIXED, "better")

    def test_a_tolerated_regression_does_not_make_it_worse(self):
        assert quality_verdict([_broke()], alpha=0.05, tolerance=1).verdict is (
            Verdict.NO_DIFFERENCE
        )
        assert quality_verdict([_broke(), _fixed()], alpha=0.05, tolerance=1).verdict is (
            Verdict.BETTER
        )

    def test_unconfirmed_flips_do_not_count(self):
        cases = [_case(True, False, candidate_reruns=[True]) for _ in range(8)]
        assert quality_verdict(cases, alpha=0.05) == QualityVerdict(Verdict.NO_DIFFERENCE)

    def test_a_different_judge_makes_the_comparison_invalid(self):
        assert quality_verdict([_broke() for _ in range(8)], alpha=0.05, invalid=True) == (
            QualityVerdict(Verdict.INVALID)
        )


class TestSettle:
    @pytest.mark.parametrize(
        ("outcomes", "settled"),
        [
            ((True,), True),
            ((False,), False),
            ((None,), None),
            ((False, True, True), True),
            ((True, False, False), False),
            ((True, None, False), None),
            ((True, None, None), True),
        ],
    )
    def test_a_case_settles_on_the_majority_of_its_decided_attempts(self, outcomes, settled):
        assert settle(outcomes) is settled


class TestSummarize:
    def test_incomplete_cases_are_kept_out_of_the_pass_rate(self):
        summary = summarize([Attempt(True), Attempt(False), Attempt(None)])
        assert (summary.cases, summary.passed, summary.failed, summary.incomplete) == (3, 1, 1, 1)
        assert summary.pass_rate == summary.first_pass_rate == 0.5

    def test_a_case_nothing_grades_is_counted_apart_from_an_incomplete_one(self):
        summary = summarize([Attempt(True), Attempt(None, ungraded=True), Attempt(None)])
        assert (summary.passed, summary.incomplete, summary.ungraded) == (1, 1, 1)
        assert summary.pass_rate == 1.0

    def test_a_crash_is_a_failure_and_counted_as_one(self):
        summary = summarize([Attempt(True), Attempt(False, crashed=True), Attempt(False)])
        assert (summary.failed, summary.crashed, summary.pass_rate) == (2, 1, 1 / 3)

    def test_a_tie_across_reruns_is_incomplete(self):
        summary = summarize([Attempt(True, reruns=(False,))])
        assert (summary.passed, summary.failed, summary.incomplete) == (0, 0, 1)

    def test_a_rerun_case_counts_as_it_settled_and_its_first_answer_aside(self):
        summary = summarize(
            [Attempt(False, reruns=(True, True)), Attempt(True), Attempt(None, reruns=())]
        )
        assert (summary.passed, summary.failed, summary.incomplete) == (2, 0, 1)
        assert summary.pass_rate == 1.0
        assert summary.first_pass_rate == 0.5

    def test_a_person_s_decision_on_the_first_answer_settles_the_case(self):
        summary = summarize([Attempt(True, reruns=(False, False), by_person=True)])
        assert summary.pass_rate == 1.0

    def test_cost_per_passed_case_and_latency_percentiles(self):
        summary = summarize(
            [
                Attempt(True, cost_usd=Decimal("0.10"), tokens=100, latency_ms=1000),
                Attempt(True, cost_usd=Decimal("0.30"), tokens=300, latency_ms=3000),
                Attempt(False, cost_usd=Decimal("0.20"), latency_ms=2000),
            ]
        )
        assert summary.cost_usd == Decimal("0.60")
        assert summary.cost_per_pass == Decimal("0.30")
        assert summary.avg_tokens == 200
        assert summary.p50_ms == 2000
        assert summary.p95_ms == pytest.approx(2900)

    def test_nothing_decided_has_no_rates(self):
        summary = summarize([Attempt(None)])
        assert summary.pass_rate is None
        assert summary.cost_per_pass is None
        assert summary.avg_tokens is None
        assert summary.p50_ms is None

    def test_each_tag_gets_its_own_summary(self):
        summary = summarize(
            [Attempt(True, tags=("billing",)), Attempt(False, tags=("billing", "refunds"))]
        )
        assert set(summary.by_tag) == {"billing", "refunds"}
        assert summary.by_tag["billing"].pass_rate == 0.5
        assert summary.by_tag["refunds"].pass_rate == 0.0
        assert summary.by_tag["billing"].by_tag == {}

    def test_percentile_of_one_value_is_that_value(self):
        assert percentile([42.0], 0.95) == 42.0


class TestTrend:
    def test_a_change_within_tolerance_is_unchanged(self):
        assert trend(1.0, 1.04, tolerance=0.05) is Trend.UNCHANGED

    def test_cheaper_is_better(self):
        assert trend(Decimal("1.00"), Decimal("0.50"), tolerance=0.05) is Trend.BETTER

    def test_slower_is_worse(self):
        assert trend(1000.0, 2000.0, tolerance=0.05) is Trend.WORSE

    def test_a_metric_where_higher_is_better(self):
        assert trend(0.5, 0.8, tolerance=0.05, lower_is_better=False) is Trend.BETTER

    def test_equal_values_are_unchanged(self):
        assert trend(0, 0, tolerance=0.05) is Trend.UNCHANGED

    def test_rising_from_zero_is_worse(self):
        assert trend(0, 1, tolerance=0.05) is Trend.WORSE

    def test_a_missing_side_is_unknown(self):
        assert trend(None, 1.0, tolerance=0.05) is Trend.UNKNOWN


class TestEfficiency:
    def test_each_metric_is_compared_on_its_own(self):
        baseline = summarize([Attempt(True, cost_usd=Decimal("1"), tokens=100, latency_ms=1000)])
        candidate = summarize([Attempt(True, cost_usd=Decimal("2"), tokens=50, latency_ms=1000)])
        trends = efficiency(baseline, candidate, tolerance=0.05)
        assert trends.cost_per_pass is Trend.WORSE
        assert trends.avg_tokens is Trend.BETTER
        assert trends.p50_ms is Trend.UNCHANGED
        assert trends.p95_ms is Trend.UNCHANGED


def test_flips_are_counted_per_tag():
    counts = flips_by_tag(
        [
            _case(True, False, tags=["billing"]),
            _case(True, True, tags=["billing", "refunds"]),
            _case(True, True),
        ]
    )
    assert counts["billing"][Flip.REGRESSION] == 1
    assert counts["billing"][Flip.UNCHANGED] == 1
    assert counts["refunds"][Flip.UNCHANGED] == 1
    assert counts["refunds"][Flip.REGRESSION] == 0
