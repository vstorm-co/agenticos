"""The rules an improvement session moves by, without I/O.

Each function takes what one step found and says where the session goes next;
`ImprovementPipelineService.advance` reads the children, calls one of these and
writes the answer in the same transaction. Keeping the rules here means every
stop reason and every verdict can be tested without a database or a model.

A session ends in `ready` at the furthest: nothing here accepts, publishes or
promotes, and no transition leaves `ready` except by a person's decision.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.db.models.authoring import AuthoringStatus
from app.db.models.background_job import JobStatus
from app.db.models.eval_run import EvalRunStatus
from app.db.models.improvement import (
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)

MIN_GRADABLE_CASES = 5
"""Gradable cases the check needs outside the evidence before a change is measured."""

INCONCLUSIVE_RERUNS = 1
"""How often an inconclusive check is run again before the session gives up."""

PROPOSAL_SECONDS = 90
"""What one round's proposal adds to a time estimate: reading the evidence and writing changes."""

ANSWER_SECONDS = 20.0
"""How long one answer is taken to take when the agent has answered nothing recently."""

STALL_MARGIN = timedelta(minutes=10)
STEP_TIMEOUT: dict[ImprovementStage, timedelta] = {
    ImprovementStage.ANALYZING: timedelta(minutes=2),
    ImprovementStage.CLASSIFYING: timedelta(minutes=10),
    ImprovementStage.DRAFTING: timedelta(minutes=15),
    ImprovementStage.PROPOSING: timedelta(hours=1),
    ImprovementStage.FILTERING: timedelta(minutes=2),
    ImprovementStage.EVALUATING: timedelta(hours=12),
    ImprovementStage.JUDGING: timedelta(minutes=2),
}
"""How long a step may run without progress: the job timeout of whatever runs it."""

QUEUED_TIMEOUT = timedelta(minutes=2)
"""How long a queued session's first step may run: the step job's own timeout."""

_MOVES: dict[ImprovementStatus, frozenset[ImprovementStatus]] = {
    ImprovementStatus.QUEUED: frozenset(
        {
            ImprovementStatus.RUNNING,
            ImprovementStatus.STOPPED,
            ImprovementStatus.FAILED,
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


def _stop(stage: ImprovementStage | None, reason: StopReason) -> Transition:
    return Transition(ImprovementStatus.STOPPED, stage, reason)


def _fail(stage: ImprovementStage | None, reason: StopReason) -> Transition:
    return Transition(ImprovementStatus.FAILED, stage, reason)


@dataclass(frozen=True)
class Pins:
    """What a session compares with, as pinned at its start or as it is now."""

    draft_hash: str
    base_version_id: UUID | None
    scoring_hash: str
    dataset_id: UUID | None
    suite_id: UUID | None
    suite_hash: str | None


def stale(pinned: Pins, current: Pins, *, archived: bool) -> bool:
    """Whether what the session is measured against changed since it started.

    A changed draft, a newer version under it, different grading, a suite whose
    threshold was edited, an archived agent, or a pinned dataset or suite that no
    longer exists - `current` names it as `None` - each mean the check would
    compare with something other than what the session promised.
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
    stage: ImprovementStage | None,
    *,
    standing: Standing,
    pinned: Pins,
    current: Pins,
    archived: bool,
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
    """Sort the bad answers once there is something to learn from and something to measure on."""
    if not has_evidence or gradable_cases < MIN_GRADABLE_CASES:
        return _stop(ImprovementStage.ANALYZING, StopReason.NO_DATA)
    return _step(ImprovementStage.CLASSIFYING)


def _ended(status: JobStatus | None) -> bool:
    """Whether a step's job is over; `None` is one retention has removed, long over."""
    return status not in ("queued", "running")


def after_classifying(
    status: JobStatus | None, *, agent_answers: int, missing_knowledge: int
) -> Transition | None:
    """Draft what is missing, or propose for what the agent got wrong; `None` while sorting.

    The two branches are each optional: answers missing knowledge are drafted
    first, then the agent's own faults are proposed for. An answer that was
    not a problem goes to neither, and one whose cause stayed unknown is the
    agent's to look at. A sort that failed leaves every answer to the agent.
    """
    if not _ended(status):
        return None
    if missing_knowledge:
        return _step(ImprovementStage.DRAFTING)
    if agent_answers:
        return _step(ImprovementStage.PROPOSING)
    return _stop(ImprovementStage.CLASSIFYING, StopReason.NO_PROPOSAL)


def after_drafting(status: JobStatus | None, *, agent_answers: int) -> Transition | None:
    """Propose for the agent's own faults after drafting; `None` while drafting.

    Drafts are for a person to add, so a session with nothing else to change
    ends there - and a drafting step that failed is that session's failure,
    while one with the agent's faults left carries on to them.
    """
    if not _ended(status):
        return None
    if agent_answers:
        return _step(ImprovementStage.PROPOSING)
    if status in ("dead", "cancelled"):
        return _fail(ImprovementStage.DRAFTING, StopReason.DRAFT)
    return _stop(ImprovementStage.DRAFTING, StopReason.KNOWLEDGE_ONLY)


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
    """The named suite's verdict on a round's check."""

    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class CheckResult:
    """What judging reads from a finished paired check.

    `comparable` is false when the check had no baseline or its comparison was
    invalid. `incomplete` counts cases on either side that ended without a
    graded answer because something other than the agent failed; `ungraded`
    counts cases nothing could grade. A crashed agent run also makes the automatic improvement decision
    inconclusive; an ordinary suite may still treat that crash as a failure. `suite` is the named suite's verdict on the same check,
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
    crashed: int = 0


def judge(result: CheckResult) -> ImprovementVerdict:
    """The verdict on a candidate. Anything not measured is inconclusive, never better.

    An automatic session needs a complete measurement before choosing its next
    candidate. A failed suite or confirmed regression decides once every case
    was measured. An ordinary suite may fail on partial evidence independently.
    """
    if result.crashed or result.incomplete or result.ungraded:
        return ImprovementVerdict.INCONCLUSIVE
    if result.suite is SuiteOutcome.FAILED:
        return ImprovementVerdict.REGRESSION
    if not result.comparable:
        return ImprovementVerdict.INCONCLUSIVE
    if result.regressions_confirmed:
        return ImprovementVerdict.REGRESSION
    if (
        result.incomplete
        or result.ungraded
        or result.candidate_pass_rate is None
        or result.baseline_pass_rate is None
        or result.suite is SuiteOutcome.INCONCLUSIVE
    ):
        return ImprovementVerdict.INCONCLUSIVE
    if result.fixed_confirmed and result.candidate_pass_rate >= result.baseline_pass_rate:
        return ImprovementVerdict.BETTER
    return ImprovementVerdict.NO_CHANGE


_STOPS = {
    ImprovementVerdict.INCONCLUSIVE: StopReason.INCONCLUSIVE,
    ImprovementVerdict.REGRESSION: StopReason.REGRESSION,
    ImprovementVerdict.NO_CHANGE: StopReason.NO_CHANGE,
}


def after_judging(
    verdict: ImprovementVerdict,
    *,
    reruns_used: int,
    spent: Decimal,
    rerun_estimate: Decimal,
    budget: Decimal,
) -> Transition:
    """Hand a better candidate to a person; check an inconclusive one once more.

    The second check is a paid step like the first, so it starts only when its
    full estimate fits what is left of the budget.
    """
    if verdict is ImprovementVerdict.BETTER:
        return Transition(ImprovementStatus.READY, ImprovementStage.JUDGING)
    if verdict is ImprovementVerdict.INCONCLUSIVE and reruns_used < INCONCLUSIVE_RERUNS:
        return before_evaluating(spent=spent, step_estimate=rerun_estimate, budget=budget)
    return _stop(ImprovementStage.JUDGING, _STOPS[verdict])


@dataclass(frozen=True)
class RoundResult:
    number: int
    verdict: ImprovementVerdict
    broken: int
    pass_rate: float | None


def best_round(rounds: list[RoundResult]) -> int | None:
    """Prefer a measured improvement, then stability and settled success.

    Inconclusive rounds are not evidence for selecting a candidate. Earlier
    rounds win exact ties, so a costly repeat cannot displace the same result.
    """
    measured = [item for item in rounds if item.verdict != ImprovementVerdict.INCONCLUSIVE]
    order = {
        ImprovementVerdict.BETTER: 2,
        ImprovementVerdict.NO_CHANGE: 1,
        ImprovementVerdict.REGRESSION: 0,
    }
    best = max(
        measured,
        key=lambda item: (
            order[item.verdict],
            -item.broken,
            item.pass_rate if item.pass_rate is not None else -1,
            -item.number,
        ),
        default=None,
    )
    return None if best is None else best.number


def round_stop(rounds: list[RoundResult], *, maximum: int) -> StopReason | None:
    """Whether another proposal can add information after this round."""
    latest = rounds[-1]
    if latest.verdict == ImprovementVerdict.BETTER:
        return None
    if len(rounds) >= 2:
        previous = rounds[-2]
        if previous.verdict == latest.verdict == ImprovementVerdict.NO_CHANGE:
            return StopReason.NO_CHANGE
        if previous.verdict == latest.verdict == ImprovementVerdict.INCONCLUSIVE:
            return StopReason.INCONCLUSIVE
    if latest.number >= maximum:
        return StopReason.MAX_ITERATIONS
    return None


def stalled(
    stage: ImprovementStage | None, *, waiting: bool, last_progress: datetime, now: datetime
) -> bool:
    """Whether a step ran longer without progress than whatever runs it is allowed to.

    `stage` is `None` for a queued session that has not taken a step yet.
    `waiting` is true while whatever runs the step - the step job, the authoring
    request or the eval run - has not been picked up yet, a retry waiting out its
    backoff included. A queue wait is never a stall, however long the pool is
    busy: a child that dies there is settled by the platform's reapers, and the
    step then ends the session on its own. `last_progress` is the later of when
    it started running and its last heartbeat, so a long eval that keeps beating
    is never stalled either.
    """
    if waiting:
        return False
    timeout = QUEUED_TIMEOUT if stage is None else STEP_TIMEOUT[stage]
    return now - last_progress > timeout + STALL_MARGIN


def stall(stage: ImprovementStage | None) -> Transition:
    """Where a stalled session goes: failed, on the step it stalled at."""
    return _fail(stage, StopReason.STALLED)


def estimated_minutes(
    *, rounds: int, answers: int, answer_seconds: float | None, concurrency: int
) -> int:
    """About how long a session takes when every round runs: one proposal, then
    every answer of its check, `concurrency` of them at a time."""
    each = ANSWER_SECONDS if answer_seconds is None else answer_seconds
    per_round = PROPOSAL_SECONDS + math.ceil(answers / max(concurrency, 1)) * each
    return max(1, math.ceil(rounds * per_round / 60))
