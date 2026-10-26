"""An improvement session's rules: what stops it, what it waits for, and a verdict
that is never "better" on anything it did not measure."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.authoring import AuthoringStatus
from app.db.models.eval_run import EvalRunStatus
from app.db.models.improvement import (
    ACTIVE_STATUSES,
    WAITING_STATUSES,
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)
from app.services.improvement_states import (
    INCONCLUSIVE_RERUNS,
    MIN_GRADABLE_CASES,
    QUEUED_TIMEOUT,
    STALL_MARGIN,
    STEP_TIMEOUT,
    CheckResult,
    Pins,
    Standing,
    SuiteOutcome,
    Transition,
    after_analyzing,
    after_classifying,
    after_drafting,
    after_evaluating,
    after_filtering,
    after_judging,
    after_proposing,
    before_evaluating,
    can_move,
    checked,
    estimated_minutes,
    judge,
    stale,
    stall,
    stalled,
)

_BETTER = CheckResult(
    comparable=True,
    incomplete=0,
    ungraded=0,
    regressions_confirmed=0,
    fixed_confirmed=3,
    candidate_pass_rate=0.8,
    baseline_pass_rate=0.6,
)
_PINS = Pins(
    draft_hash="a" * 64,
    base_version_id=uuid.uuid4(),
    scoring_hash="s" * 64,
    dataset_id=uuid.uuid4(),
    suite_id=uuid.uuid4(),
    suite_hash="h" * 64,
)
_BUDGET = {"spent": Decimal("0.01"), "rerun_estimate": Decimal("0.01"), "budget": Decimal("0.04")}
_ALLOWED = Standing(
    member=True, edits_agent=True, views_runs=True, runs_dataset=True, ai_assistance=True
)


def test_a_measured_improvement_is_better() -> None:
    assert judge(_BETTER) is ImprovementVerdict.BETTER


def test_an_equal_pass_rate_with_confirmed_fixes_is_still_better() -> None:
    assert judge(replace(_BETTER, candidate_pass_rate=0.6)) is ImprovementVerdict.BETTER


@pytest.mark.parametrize(
    "result",
    [
        replace(_BETTER, incomplete=1),
        replace(_BETTER, ungraded=1),
        replace(_BETTER, comparable=False),
        replace(_BETTER, candidate_pass_rate=None),
        replace(_BETTER, baseline_pass_rate=None),
        replace(_BETTER, suite=SuiteOutcome.INCONCLUSIVE),
    ],
    ids=["infrastructure-failed", "nothing-grades", "invalid", "no-candidate", "no-base", "suite"],
)
def test_a_check_that_did_not_measure_everything_is_inconclusive(result: CheckResult) -> None:
    """D1: an ungraded case or a provider failure never lets a candidate count as better."""
    assert judge(result) is ImprovementVerdict.INCONCLUSIVE


@pytest.mark.parametrize(
    "result",
    [
        replace(_BETTER, ungraded=2, regressions_confirmed=1),
        replace(_BETTER, incomplete=1, suite=SuiteOutcome.FAILED),
    ],
    ids=["confirmed-regression", "failed-suite"],
)
def test_partial_measurement_keeps_an_automatic_session_inconclusive(result: CheckResult) -> None:
    """A partial check never lets an automatic session select its candidate."""
    assert judge(result) is ImprovementVerdict.INCONCLUSIVE


def test_an_invalid_comparison_says_nothing_even_about_regressions() -> None:
    result = replace(_BETTER, comparable=False, regressions_confirmed=2)
    assert judge(result) is ImprovementVerdict.INCONCLUSIVE


def test_a_failed_suite_decides_even_when_the_sides_cannot_be_compared() -> None:
    """A suite's pass-rate floor is absolute, so it fails without a valid comparison."""
    result = replace(_BETTER, comparable=False, suite=SuiteOutcome.FAILED)
    assert judge(result) is ImprovementVerdict.REGRESSION


def test_a_confirmed_regression_outweighs_the_fixes() -> None:
    assert judge(replace(_BETTER, regressions_confirmed=1)) is ImprovementVerdict.REGRESSION


def test_a_failed_suite_is_a_regression_even_with_fixes() -> None:
    result = replace(_BETTER, suite=SuiteOutcome.FAILED)
    assert judge(result) is ImprovementVerdict.REGRESSION


def test_a_passed_suite_lets_a_better_candidate_through() -> None:
    result = replace(_BETTER, suite=SuiteOutcome.PASSED)
    assert judge(result) is ImprovementVerdict.BETTER


@pytest.mark.parametrize(
    "result",
    [
        replace(_BETTER, fixed_confirmed=0),
        replace(_BETTER, candidate_pass_rate=0.5),
    ],
    ids=["nothing-fixed", "lower-pass-rate"],
)
def test_no_confirmed_fix_or_a_lower_pass_rate_is_no_change(result: CheckResult) -> None:
    assert judge(result) is ImprovementVerdict.NO_CHANGE


def test_a_better_candidate_waits_for_a_person() -> None:
    move = after_judging(ImprovementVerdict.BETTER, reruns_used=0, **_BUDGET)
    assert move == Transition(ImprovementStatus.READY, ImprovementStage.JUDGING)


def test_an_inconclusive_check_is_run_once_more() -> None:
    move = after_judging(ImprovementVerdict.INCONCLUSIVE, reruns_used=0, **_BUDGET)
    assert move == Transition(ImprovementStatus.RUNNING, ImprovementStage.EVALUATING)


@pytest.mark.security
def test_an_inconclusive_check_is_not_rerun_past_the_budget() -> None:
    """D12: the rerun is a paid step, held to the budget before it starts like the first check."""
    move = after_judging(
        ImprovementVerdict.INCONCLUSIVE,
        reruns_used=0,
        spent=Decimal("0.03"),
        rerun_estimate=Decimal("0.02"),
        budget=Decimal("0.04"),
    )
    assert move == Transition(
        ImprovementStatus.STOPPED, ImprovementStage.EVALUATING, StopReason.BUDGET
    )


def test_a_second_inconclusive_check_stops_the_session() -> None:
    move = after_judging(
        ImprovementVerdict.INCONCLUSIVE, reruns_used=INCONCLUSIVE_RERUNS, **_BUDGET
    )
    assert move == Transition(
        ImprovementStatus.STOPPED, ImprovementStage.JUDGING, StopReason.INCONCLUSIVE
    )


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [
        (ImprovementVerdict.REGRESSION, StopReason.REGRESSION),
        (ImprovementVerdict.NO_CHANGE, StopReason.NO_CHANGE),
    ],
)
def test_a_candidate_that_is_not_better_stops_with_its_verdict(
    verdict: ImprovementVerdict, reason: StopReason
) -> None:
    move = after_judging(verdict, reruns_used=0, **_BUDGET)
    assert move == Transition(ImprovementStatus.STOPPED, ImprovementStage.JUDGING, reason)


def test_analysis_with_evidence_and_enough_cases_sorts_the_bad_answers() -> None:
    move = after_analyzing(has_evidence=True, gradable_cases=MIN_GRADABLE_CASES)
    assert move == Transition(ImprovementStatus.RUNNING, ImprovementStage.CLASSIFYING)


@pytest.mark.parametrize(
    ("has_evidence", "gradable_cases"),
    [(False, 10), (True, MIN_GRADABLE_CASES - 1)],
    ids=["nothing-rated", "too-few-cases"],
)
def test_analysis_without_something_to_learn_from_or_measure_on_stops(
    *, has_evidence: bool, gradable_cases: int
) -> None:
    move = after_analyzing(has_evidence=has_evidence, gradable_cases=gradable_cases)
    assert move == Transition(
        ImprovementStatus.STOPPED, ImprovementStage.ANALYZING, StopReason.NO_DATA
    )


@pytest.mark.parametrize("status", [AuthoringStatus.QUEUED, AuthoringStatus.RUNNING])
def test_proposing_waits_for_the_request(status: AuthoringStatus) -> None:
    assert after_proposing(status, hunks=0) is None


def test_a_failed_request_fails_the_session() -> None:
    assert after_proposing(AuthoringStatus.FAILED, hunks=2) == Transition(
        ImprovementStatus.FAILED, ImprovementStage.PROPOSING, StopReason.PROPOSAL
    )


def test_a_request_that_proposed_nothing_stops_the_session() -> None:
    assert after_proposing(AuthoringStatus.COMPLETED, hunks=0) == Transition(
        ImprovementStatus.STOPPED, ImprovementStage.PROPOSING, StopReason.NO_PROPOSAL
    )


def test_a_proposal_goes_to_the_filter() -> None:
    assert after_proposing(AuthoringStatus.COMPLETED, hunks=2) == Transition(
        ImprovementStatus.RUNNING, ImprovementStage.FILTERING
    )


def test_a_candidate_the_policy_emptied_is_not_checked() -> None:
    assert after_filtering(kept=0) == Transition(
        ImprovementStatus.STOPPED, ImprovementStage.FILTERING, StopReason.NO_PROPOSAL
    )
    assert after_filtering(kept=1) == Transition(
        ImprovementStatus.RUNNING, ImprovementStage.EVALUATING
    )


@pytest.mark.security
def test_a_check_starts_only_when_it_fits_the_remaining_budget() -> None:
    """D12: the full estimate is held to what is left before the step, not during it."""
    fits = before_evaluating(
        spent=Decimal("0.02"), step_estimate=Decimal("0.03"), budget=Decimal("0.05")
    )
    over = before_evaluating(
        spent=Decimal("0.03"), step_estimate=Decimal("0.03"), budget=Decimal("0.05")
    )
    assert fits == Transition(ImprovementStatus.RUNNING, ImprovementStage.EVALUATING)
    assert over == Transition(
        ImprovementStatus.STOPPED, ImprovementStage.EVALUATING, StopReason.BUDGET
    )


@pytest.mark.parametrize("status", [EvalRunStatus.QUEUED, EvalRunStatus.RUNNING])
def test_evaluating_waits_for_the_check(status: EvalRunStatus) -> None:
    assert after_evaluating(status) is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (
            EvalRunStatus.COMPLETED,
            Transition(ImprovementStatus.RUNNING, ImprovementStage.JUDGING),
        ),
        (
            EvalRunStatus.BUDGET_EXCEEDED,
            Transition(ImprovementStatus.STOPPED, ImprovementStage.EVALUATING, StopReason.BUDGET),
        ),
        (
            EvalRunStatus.FAILED,
            Transition(ImprovementStatus.FAILED, ImprovementStage.EVALUATING, StopReason.EVAL),
        ),
        (
            EvalRunStatus.CANCELLED,
            Transition(ImprovementStatus.FAILED, ImprovementStage.EVALUATING, StopReason.EVAL),
        ),
    ],
)
def test_a_finished_check_is_judged_or_ends_the_session(
    status: EvalRunStatus, expected: Transition
) -> None:
    assert after_evaluating(status) == expected


def test_nothing_changed_is_not_stale() -> None:
    assert not stale(_PINS, _PINS, archived=False)


@pytest.mark.parametrize(
    "current",
    [
        replace(_PINS, draft_hash="b" * 64),
        replace(_PINS, base_version_id=uuid.uuid4()),
        replace(_PINS, scoring_hash="t" * 64),
        replace(_PINS, dataset_id=None),
        replace(_PINS, suite_id=None),
        replace(_PINS, suite_hash="i" * 64),
    ],
    ids=[
        "draft-edited",
        "published",
        "grading-changed",
        "dataset-deleted",
        "suite-deleted",
        "suite-edited",
    ],
)
def test_a_changed_base_or_grading_is_stale(current: Pins) -> None:
    assert stale(_PINS, current, archived=False)


def test_an_archived_agent_is_stale() -> None:
    assert stale(_PINS, _PINS, archived=True)


def test_a_session_in_good_standing_carries_on() -> None:
    move = checked(
        ImprovementStage.PROPOSING, standing=_ALLOWED, pinned=_PINS, current=_PINS, archived=False
    )
    assert move is None


@pytest.mark.parametrize(
    "standing",
    [
        replace(_ALLOWED, member=False),
        replace(_ALLOWED, edits_agent=False),
        replace(_ALLOWED, views_runs=False),
        replace(_ALLOWED, runs_dataset=False),
        replace(_ALLOWED, ai_assistance=False),
    ],
    ids=["left", "no-edit", "no-runs-view", "no-dataset-run", "ai-off"],
)
@pytest.mark.security
def test_losing_access_stops_the_session_with_permission(standing: Standing) -> None:
    move = checked(
        ImprovementStage.EVALUATING,
        standing=standing,
        pinned=_PINS,
        current=replace(_PINS, draft_hash="b" * 64),
        archived=False,
    )
    assert move == Transition(
        ImprovementStatus.STOPPED, ImprovementStage.EVALUATING, StopReason.PERMISSION
    )


def test_a_change_under_the_session_makes_it_stale() -> None:
    move = checked(
        ImprovementStage.FILTERING,
        standing=_ALLOWED,
        pinned=_PINS,
        current=replace(_PINS, draft_hash="b" * 64),
        archived=False,
    )
    assert move == Transition(ImprovementStatus.STALE, ImprovementStage.FILTERING, StopReason.STALE)


@pytest.mark.parametrize("stage", [None, *ImprovementStage])
def test_a_running_step_stalls_only_after_its_timeout_and_the_margin(
    stage: ImprovementStage | None,
) -> None:
    now = datetime.now(UTC)
    limit = (QUEUED_TIMEOUT if stage is None else STEP_TIMEOUT[stage]) + STALL_MARGIN
    assert not stalled(stage, waiting=False, last_progress=now - limit, now=now)
    assert stalled(stage, waiting=False, last_progress=now - limit - timedelta(seconds=1), now=now)


@pytest.mark.parametrize("stage", [None, ImprovementStage.PROPOSING, ImprovementStage.EVALUATING])
def test_a_step_waiting_in_a_queue_never_stalls(stage: ImprovementStage | None) -> None:
    """A check queued behind long evals for a day is still alive, and must not be paid for twice."""
    now = datetime.now(UTC)
    assert not stalled(stage, waiting=True, last_progress=now - timedelta(days=2), now=now)


@pytest.mark.parametrize("stage", [None, ImprovementStage.EVALUATING])
def test_a_stalled_session_fails_where_it_stalled(stage: ImprovementStage | None) -> None:
    """A queued session whose step job died fails too, and frees the agent for a new one."""
    assert stall(stage) == Transition(ImprovementStatus.FAILED, stage, StopReason.STALLED)
    assert can_move(ImprovementStatus.QUEUED, ImprovementStatus.FAILED)


def test_every_step_has_a_timeout() -> None:
    assert set(STEP_TIMEOUT) == set(ImprovementStage)


def _moves(status: ImprovementStatus) -> set[ImprovementStatus]:
    return {to for to in ImprovementStatus if can_move(status, to)}


@pytest.mark.parametrize("status", [ImprovementStatus.PUBLISHED, ImprovementStatus.REJECTED])
def test_a_decided_session_never_moves_again(status: ImprovementStatus) -> None:
    assert _moves(status) == set()


@pytest.mark.parametrize("status", [ImprovementStatus.STALE, ImprovementStatus.CANCELLED])
def test_a_session_that_is_over_can_only_be_discarded(status: ImprovementStatus) -> None:
    assert _moves(status) == {ImprovementStatus.REJECTED}


def test_an_accepted_session_is_published_or_taken_back() -> None:
    assert _moves(ImprovementStatus.ACCEPTED) == {
        ImprovementStatus.READY,
        ImprovementStatus.PUBLISHED,
        ImprovementStatus.REJECTED,
    }


def test_a_queued_session_starts_or_ends() -> None:
    assert _moves(ImprovementStatus.QUEUED) == {
        ImprovementStatus.RUNNING,
        ImprovementStatus.STOPPED,
        ImprovementStatus.FAILED,
        ImprovementStatus.STALE,
        ImprovementStatus.CANCELLED,
    }


def test_a_running_session_moves_on_or_ends_but_never_decides_for_a_person() -> None:
    assert _moves(ImprovementStatus.RUNNING) == {
        ImprovementStatus.RUNNING,
        ImprovementStatus.READY,
        ImprovementStatus.STOPPED,
        ImprovementStatus.FAILED,
        ImprovementStatus.STALE,
        ImprovementStatus.CANCELLED,
    }


def test_a_stopped_or_failed_session_goes_on_only_when_a_person_asks() -> None:
    assert _moves(ImprovementStatus.STOPPED) == {
        ImprovementStatus.RUNNING,
        ImprovementStatus.READY,
        ImprovementStatus.STALE,
        ImprovementStatus.CANCELLED,
        ImprovementStatus.REJECTED,
    }
    assert _moves(ImprovementStatus.FAILED) == {
        ImprovementStatus.RUNNING,
        ImprovementStatus.REJECTED,
    }


def test_only_a_measured_candidate_waits_for_a_person() -> None:
    reaching = {s for s in ImprovementStatus if can_move(s, ImprovementStatus.READY)}
    assert reaching == {
        ImprovementStatus.RUNNING,
        ImprovementStatus.READY,
        ImprovementStatus.STOPPED,
        ImprovementStatus.ACCEPTED,
    }
    decided = {ImprovementStatus.ACCEPTED, ImprovementStatus.PUBLISHED}
    assert {s for s in ImprovementStatus if _moves(s) & decided} == {
        ImprovementStatus.READY,
        ImprovementStatus.ACCEPTED,
    }


def test_statuses_split_into_active_waiting_and_finished() -> None:
    assert ACTIVE_STATUSES == (ImprovementStatus.QUEUED, ImprovementStatus.RUNNING)
    assert WAITING_STATUSES == (ImprovementStatus.READY, ImprovementStatus.ACCEPTED)
    for status in ImprovementStatus:
        assert [status.active, status.waiting, status.terminal].count(True) == 1


@pytest.mark.parametrize("status", ["queued", "running"])
def test_sorting_and_drafting_wait_for_their_jobs(status) -> None:
    assert after_classifying(status, agent_answers=1, missing_knowledge=1) is None
    assert after_drafting(status, agent_answers=1) is None


@pytest.mark.parametrize(
    ("agent_answers", "missing_knowledge", "stage"),
    [
        (2, 1, ImprovementStage.DRAFTING),
        (0, 3, ImprovementStage.DRAFTING),
        (2, 0, ImprovementStage.PROPOSING),
    ],
    ids=["both", "only-gaps", "only-the-agent"],
)
def test_missing_knowledge_is_drafted_first_and_the_agents_faults_proposed_for(
    agent_answers, missing_knowledge, stage
) -> None:
    move = after_classifying(
        "succeeded", agent_answers=agent_answers, missing_knowledge=missing_knowledge
    )
    assert move == Transition(ImprovementStatus.RUNNING, stage)


@pytest.mark.parametrize("status", ["succeeded", "dead", None])
def test_a_round_with_nothing_to_fix_proposes_nothing(status) -> None:
    move = after_classifying(status, agent_answers=0, missing_knowledge=0)
    assert move == Transition(
        ImprovementStatus.STOPPED, ImprovementStage.CLASSIFYING, StopReason.NO_PROPOSAL
    )


@pytest.mark.parametrize(
    ("status", "agent_answers", "move"),
    [
        ("succeeded", 1, Transition(ImprovementStatus.RUNNING, ImprovementStage.PROPOSING)),
        ("dead", 1, Transition(ImprovementStatus.RUNNING, ImprovementStage.PROPOSING)),
        (
            "succeeded",
            0,
            Transition(
                ImprovementStatus.STOPPED, ImprovementStage.DRAFTING, StopReason.KNOWLEDGE_ONLY
            ),
        ),
        (
            None,
            0,
            Transition(
                ImprovementStatus.STOPPED, ImprovementStage.DRAFTING, StopReason.KNOWLEDGE_ONLY
            ),
        ),
        (
            "cancelled",
            0,
            Transition(ImprovementStatus.FAILED, ImprovementStage.DRAFTING, StopReason.DRAFT),
        ),
    ],
    ids=["then-the-agent", "failed-then-the-agent", "only-gaps", "job-long-gone", "failed"],
)
def test_after_drafting_the_agents_faults_are_next_or_the_session_ends(
    status, agent_answers, move
) -> None:
    assert after_drafting(status, agent_answers=agent_answers) == move


def test_an_agent_crash_is_a_failure_and_only_missing_grades_are_inconclusive() -> None:
    assert judge(replace(_BETTER, crashed=2)) is ImprovementVerdict.BETTER
    assert (
        judge(replace(_BETTER, crashed=2, regressions_confirmed=2)) is ImprovementVerdict.REGRESSION
    )
    assert judge(replace(_BETTER, crashed=2, incomplete=1)) is ImprovementVerdict.INCONCLUSIVE


def test_best_round_prefers_quality_stability_success_then_the_earlier_round() -> None:
    from app.services.improvement_states import RoundResult, best_round

    rounds = [
        RoundResult(1, ImprovementVerdict.REGRESSION, 1, 0.9),
        RoundResult(2, ImprovementVerdict.NO_CHANGE, 0, 0.8),
        RoundResult(3, ImprovementVerdict.BETTER, 0, 0.9),
    ]
    assert best_round(rounds) == 3
    assert best_round(rounds[:2]) == 2
    assert best_round([*rounds, RoundResult(4, ImprovementVerdict.BETTER, 0, 0.9)]) == 3
    assert best_round([RoundResult(1, ImprovementVerdict.INCONCLUSIVE, 0, None)]) is None


@pytest.mark.parametrize(
    ("verdicts", "maximum", "reason"),
    [
        (["regression"], 3, None),
        (["no_change", "no_change"], 3, StopReason.NO_CHANGE),
        (["inconclusive", "inconclusive"], 3, StopReason.INCONCLUSIVE),
        (["regression", "no_change", "regression"], 3, StopReason.MAX_ITERATIONS),
        (["better"], 1, None),
    ],
)
def test_round_stop_conditions(verdicts, maximum, reason) -> None:
    from app.services.improvement_states import RoundResult, round_stop

    assert (
        round_stop(
            [
                RoundResult(index + 1, ImprovementVerdict(verdict), 0, 0.8)
                for index, verdict in enumerate(verdicts)
            ],
            maximum=maximum,
        )
        == reason
    )


def test_a_session_is_timed_by_its_rounds_and_how_many_answers_run_at_once() -> None:
    assert estimated_minutes(rounds=1, answers=12, answer_seconds=10.0, concurrency=3) == 3
    assert estimated_minutes(rounds=3, answers=12, answer_seconds=10.0, concurrency=3) == 7
    assert estimated_minutes(rounds=1, answers=12, answer_seconds=10.0, concurrency=12) == 2


def test_an_agent_with_no_recent_answers_is_timed_by_the_default() -> None:
    assert estimated_minutes(rounds=1, answers=6, answer_seconds=None, concurrency=3) == 3
    assert estimated_minutes(rounds=1, answers=0, answer_seconds=0.0, concurrency=0) == 2
