"""Holding one eval run to a suite's threshold.

Quality decides first: the settled pass rate against its minimum and the
confirmed regressions against their maximum - zero unless the owner allowed
more, so one case that breaks reproducibly fails the suite. The McNemar
direction a comparison reports is shown beside the result and never decides it:
on the five to twenty cases a dataset usually holds, it cannot tell, and a
regression somebody can reproduce is a regression whatever the test says.

Efficiency is the second axis and is checked only where the owner set a
ceiling: a rise in cost per passed case or in p95 latency against the baseline.
A comparison the two sides of which were graded differently decides nothing
beyond the minimum pass rate, which never needed a baseline. Nor does a run with
a case left undecided - nothing grades it, or the provider or a scorer failed on
it - unless something failed outright: a confirmed regression, or a minimum the
pass rate misses even were every undecided case to pass. Such a result is
inconclusive, never passed, until every case has a verdict.

A case the agent crashed on is not undecided: it failed, counts against the
pass rate, and fails the result outright as a confirmed regression does - a
crash needs no baseline and no minimum to be a defect.
"""

from decimal import Decimal
from math import inf, isinf

from app.db.models.eval_suite import EvalSuiteResultStatus
from app.schemas.eval_run import ArmSummaryRead, EvalComparisonRead
from app.schemas.eval_suite import EvalSuiteThreshold, ThresholdReason


def rise(candidate: Decimal | float | None, baseline: Decimal | float | None) -> float | None:
    """How much larger the candidate is than the baseline, as a fraction of it."""
    if candidate is None or baseline is None:
        return None
    if baseline == 0:
        return inf if candidate > 0 else 0.0
    if baseline < 0:
        return None
    return float(candidate) / float(baseline) - 1


def judge(
    threshold: EvalSuiteThreshold,
    summary: ArmSummaryRead,
    comparison: EvalComparisonRead,
) -> tuple[EvalSuiteResultStatus, list[ThresholdReason]]:
    """Whether a run meets the threshold, and every way it does not.

    `summary` is the candidate over every case it was asked, the ones left
    undecided counted apart; `comparison` is the candidate against its
    baseline, over the cases both answered.
    """
    if summary.pass_rate is None:
        if summary.crashed:
            return EvalSuiteResultStatus.FAILED, [
                ThresholdReason(code="crashed", value=summary.crashed)
            ]
        return EvalSuiteResultStatus.INCONCLUSIVE, [
            ThresholdReason(code="nothing_graded", limit=threshold.min_pass_rate)
        ]
    reasons: list[ThresholdReason] = []
    open_cases: list[ThresholdReason] = []
    if threshold.min_pass_rate is not None and summary.pass_rate < threshold.min_pass_rate:
        below = ThresholdReason(
            code="pass_rate_below", value=summary.pass_rate, limit=threshold.min_pass_rate
        )
        best = (summary.cases - summary.failed) / summary.cases
        (open_cases if best >= threshold.min_pass_rate else reasons).append(below)
    if summary.crashed:
        reasons.append(ThresholdReason(code="crashed", value=summary.crashed))
    if summary.incomplete:
        open_cases.append(ThresholdReason(code="incomplete", value=summary.incomplete))
    if summary.ungraded:
        open_cases.append(ThresholdReason(code="ungraded", value=summary.ungraded))
    if comparison.verdict == "invalid":
        if reasons:
            return EvalSuiteResultStatus.FAILED, reasons
        return EvalSuiteResultStatus.INCONCLUSIVE, [
            ThresholdReason(code="invalid_comparison", detail=comparison.invalid_reason),
            *open_cases,
        ]
    if (
        comparison.baseline is not None
        and comparison.regressions_confirmed > threshold.max_confirmed_regressions
    ):
        reasons.append(
            ThresholdReason(
                code="regressions",
                value=comparison.regressions_confirmed,
                limit=threshold.max_confirmed_regressions,
            )
        )
    theirs = comparison.baseline_summary
    if theirs is not None:
        mine = comparison.candidate_summary
        ceilings = (
            (
                "cost_per_pass_rise",
                threshold.max_cost_per_pass_rise,
                mine.cost_per_pass_usd,
                theirs.cost_per_pass_usd,
            ),
            ("p95_rise", threshold.max_p95_rise, mine.p95_ms, theirs.p95_ms),
        )
        # An undecided case may yet pass and answer, which moves both numbers.
        provisional = summary.incomplete or summary.ungraded
        for code, ceiling, candidate, baseline in ceilings:
            grew = rise(candidate, baseline)
            if ceiling is not None and grew is not None and grew > ceiling:
                (open_cases if provisional else reasons).append(
                    ThresholdReason(
                        code=code,
                        value=None if isinf(grew) else round(grew, 4),
                        limit=ceiling,
                        detail="zero_baseline" if isinf(grew) else None,
                    )
                )
    if reasons:
        return EvalSuiteResultStatus.FAILED, reasons
    if open_cases:
        return EvalSuiteResultStatus.INCONCLUSIVE, open_cases
    if threshold.min_pass_rate is None and comparison.baseline is None:
        return EvalSuiteResultStatus.BASELINE_SET, []
    return EvalSuiteResultStatus.PASSED, []
