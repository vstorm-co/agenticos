"""The rules an improvement session moves by, without I/O.

Each function takes what one step found and says where the session goes next;
`ImprovementPipelineService.advance` reads the children, calls one of these and
writes the answer in the same transaction. Keeping the rules here means every
stop reason and every verdict can be tested without a database or a model.

A session ends in `ready` at the furthest: nothing here accepts, publishes or
promotes, and no transition leaves `ready` except by a person's decision.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.db.models.authoring import AuthoringStatus
from app.db.models.eval_run import EvalRunStatus
from app.db.models.improvement import (
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)

MIN_GRADABLE_CASES = 3
"""Gradable cases the check needs outside the evidence before a change is measured."""

INCONCLUSIVE_RERUNS = 1
"""How often an inconclusive check is run again before the session gives up."""

STALL_MARGIN = timedelta(minutes=10)
STEP_TIMEOUT: dict[ImprovementStage, timedelta] = {
    ImprovementStage.ANALYZING: timedelta(minutes=2),
    ImprovementStage.PROPOSING: timedelta(hours=1),
    ImprovementStage.FILTERING: timedelta(minutes=2),
    ImprovementStage.EVALUATING: timedelta(hours=12),
    ImprovementStage.JUDGING: timedelta(minutes=2),
}
"""How long a step may go without progress: the job timeout of whatever does it."""

_MOVES: dict[ImprovementStatus, frozenset[ImprovementStatus]] = {
    ImprovementStatus.QUEUED: frozenset(
        {
            ImprovementStatus.RUNNING,
            ImprovementStatus.STOPPED,
            ImprovementStatus.STALE,
            ImprovementStatus.CANCELLED,
        }
    ),
    ImprovementStatus.RUNNING: frozenset(
        {
            ImprovementStatus.RUNNING,
            ImprovementStatus.READY,
            ImprovementStatus.STOPPED,
            ImprovementStatus.FAILED,
            ImprovementStatus.STALE,
            ImprovementStatus.CANCELLED,
        }
    ),
    ImprovementStatus.READY: frozenset(
        {ImprovementStatus.ACCEPTED, ImprovementStatus.PUBLISHED, ImprovementStatus.REJECTED}
    ),
    ImprovementStatus.ACCEPTED: frozenset({ImprovementStatus.PUBLISHED}),
}


def can_move(current: ImprovementStatus, to: ImprovementStatus) -> bool:
    """Whether a session in `current` may be written as `to`."""
    return to in _MOVES.get(current, frozenset())


@dataclass(frozen=True)
class Transition:
    """Where a session goes: its status, the step it is on and why it stopped."""

    status: ImprovementStatus
    stage: ImprovementStage | None
    stop_reason: StopReason | None = None


def _step(stage: ImprovementStage) -> Transition:
    return Transition(ImprovementStatus.RUNNING, stage)


def _stop(stage: ImprovementStage, reason: StopReason) -> Transition:
    return Transition(ImprovementStatus.STOPPED, stage, reason)


def _fail(stage: ImprovementStage, reason: StopReason) -> Transition:
    return Transition(ImprovementStatus.FAILED, stage, reason)


@dataclass(frozen=True)
class Pins:
    """What a session compares with, as pinned at its start or as it is now."""

    draft_hash: str
    base_version_id: UUID | None
    scoring_hash: str


def stale(pinned: Pins, current: Pins, *, archived: bool) -> bool:
    """Whether what the session is measured against changed since it started.

    A changed draft, a newer version under it, different grading or an archived
    agent each mean the check would compare with a base that no longer exists.
    """
    return archived or pinned != current


@dataclass(frozen=True)
class Standing:
    """Whether the person the session acts for may still do what it does."""

    member: bool
    edits_agent: bool
    views_runs: bool
    runs_dataset: bool
    ai_assistance: bool

    @property
    def allowed(self) -> bool:
        return (
            self.member
            and self.edits_agent
            and self.views_runs
            and self.runs_dataset
            and self.ai_assistance
        )


def checked(
    stage: ImprovementStage, *, standing: Standing, pinned: Pins, current: Pins, archived: bool
) -> Transition | None:
    """The stop a session takes before any step, or `None` to carry on.

    Permission is checked first: a person who lost access is told so, whatever
    else changed.
    """
    if not standing.allowed:
        return _stop(stage, StopReason.PERMISSION)
    if stale(pinned, current, archived=archived):
        return Transition(ImprovementStatus.STALE, stage, StopReason.STALE)
    return None


def after_analyzing(*, has_evidence: bool, gradable_cases: int) -> Transition:
    """Propose once there is something to learn from and something to measure on."""
    if not has_evidence or gradable_cases < MIN_GRADABLE_CASES:
        return _stop(ImprovementStage.ANALYZING, StopReason.NO_DATA)
    return _step(ImprovementStage.PROPOSING)


def after_proposing(status: AuthoringStatus, *, hunks: int) -> Transition | None:
    """Filter what the assistant proposed; `None` while its request is still going."""
    if status in (AuthoringStatus.QUEUED, AuthoringStatus.RUNNING):
        return None
    if status is AuthoringStatus.FAILED:
        return _fail(ImprovementStage.PROPOSING, StopReason.PROPOSAL)
    if hunks == 0:
        return _stop(ImprovementStage.PROPOSING, StopReason.NO_PROPOSAL)
    return _step(ImprovementStage.FILTERING)


def after_filtering(*, kept: int) -> Transition:
    """Check the candidate, unless the policy left nothing in it."""
    if kept == 0:
        return _stop(ImprovementStage.FILTERING, StopReason.NO_PROPOSAL)
    return _step(ImprovementStage.EVALUATING)


def affordable(*, spent: Decimal, step_estimate: Decimal, budget: Decimal) -> bool:
    """Whether a paid step's full estimate fits what is left of the budget.

    Checked before the step only. A step that started runs to its end, whatever
    it costs, so the estimate must already include reruns and the baseline.
    """
    return spent + step_estimate <= budget


def before_evaluating(*, spent: Decimal, step_estimate: Decimal, budget: Decimal) -> Transition:
    """Start the check, or stop without starting it when it does not fit the budget."""
    if not affordable(spent=spent, step_estimate=step_estimate, budget=budget):
        return _stop(ImprovementStage.EVALUATING, StopReason.BUDGET)
    return _step(ImprovementStage.EVALUATING)


def after_evaluating(status: EvalRunStatus) -> Transition | None:
    """Judge a finished check; `None` while it is still going."""
    if not status.terminal:
        return None
    if status is EvalRunStatus.COMPLETED:
        return _step(ImprovementStage.JUDGING)
    if status is EvalRunStatus.BUDGET_EXCEEDED:
        return _stop(ImprovementStage.EVALUATING, StopReason.BUDGET)
    return _fail(ImprovementStage.EVALUATING, StopReason.EVAL)


class SuiteOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class CheckResult:
    """What judging reads from a finished paired check.

    `comparable` is false when the check had no baseline or its comparison was
    invalid. `incomplete` counts cases on either side that ended without a
    graded answer because something other than the agent failed; `ungraded`
    counts cases nothing could grade. A crashed agent run is a failed case and
    counts in neither. `suite` is the named suite's verdict on the same check,
    or `None` when the session names no suite.
    """

    comparable: bool
    incomplete: int
    ungraded: int
    regressions_confirmed: int
    fixed_confirmed: int
    candidate_pass_rate: float | None
    baseline_pass_rate: float | None
    suite: SuiteOutcome | None = None


def judge(result: CheckResult) -> ImprovementVerdict:
    """The verdict on a candidate. Anything not measured is inconclusive, never better."""
    if (
        not result.comparable
        or result.incomplete
        or result.ungraded
        or result.candidate_pass_rate is None
        or result.baseline_pass_rate is None
        or result.suite is SuiteOutcome.INCONCLUSIVE
    ):
        return ImprovementVerdict.INCONCLUSIVE
    if result.regressions_confirmed or result.suite is SuiteOutcome.FAILED:
        return ImprovementVerdict.REGRESSION
    if result.fixed_confirmed and result.candidate_pass_rate >= result.baseline_pass_rate:
        return ImprovementVerdict.BETTER
    return ImprovementVerdict.NO_CHANGE


_STOPS = {
    ImprovementVerdict.INCONCLUSIVE: StopReason.INCONCLUSIVE,
    ImprovementVerdict.REGRESSION: StopReason.REGRESSION,
    ImprovementVerdict.NO_CHANGE: StopReason.NO_CHANGE,
}


def after_judging(verdict: ImprovementVerdict, *, reruns_used: int) -> Transition:
    """Hand a better candidate to a person; check an inconclusive one once more."""
    if verdict is ImprovementVerdict.BETTER:
        return Transition(ImprovementStatus.READY, ImprovementStage.JUDGING)
    if verdict is ImprovementVerdict.INCONCLUSIVE and reruns_used < INCONCLUSIVE_RERUNS:
        return _step(ImprovementStage.EVALUATING)
    return _stop(ImprovementStage.JUDGING, _STOPS[verdict])


def stalled(stage: ImprovementStage, *, last_progress: datetime, now: datetime) -> bool:
    """Whether a step went longer without progress than whatever runs it is allowed to.

    `last_progress` is the later of the step's start and its child's last
    heartbeat, so a long eval that keeps beating is never stalled.
    """
    return now - last_progress > STEP_TIMEOUT[stage] + STALL_MARGIN
