"""The rules an improvement session moves by, without I/O.

Each function takes what one step found and says where the session goes next;
`ImprovementPipelineService.advance` reads the children, calls one of these and
writes the answer in the same transaction. Keeping the rules here means every
stop reason and every verdict can be tested without a database or a model.

A session ends in `ready` at the furthest: nothing here accepts, publishes or
promotes, and no transition leaves `ready` except by a person's decision. A
session also waits for a person after sorting the bad answers and after
filtering what was proposed, so each paid step after those is one somebody took.
"""

import math
from collections.abc import Sequence
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
from app.schemas.improvement import (
    AttemptNoise,
    MeasurementNoise,
    NoisyAttempt,
    NoisyQuestion,
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

_ENDS = frozenset(
    {
        ImprovementStatus.STOPPED,
        ImprovementStatus.FAILED,
        ImprovementStatus.STALE,
        ImprovementStatus.CANCELLED,
    }
)
_MOVES: dict[ImprovementStatus, frozenset[ImprovementStatus]] = {
    ImprovementStatus.QUEUED: _ENDS | {ImprovementStatus.RUNNING},
    ImprovementStatus.RUNNING: _ENDS
    | {ImprovementStatus.RUNNING, ImprovementStatus.WAITING, ImprovementStatus.READY},
    # The next step a person took, the same stop seen again, or the session ended.
    ImprovementStatus.WAITING: frozenset(
        {
            ImprovementStatus.RUNNING,
            ImprovementStatus.WAITING,
            ImprovementStatus.STALE,
            ImprovementStatus.CANCELLED,
            ImprovementStatus.REJECTED,
        }
    ),
    # A person's decision, or one they asked for: another round or a recheck
    # (running), another measured round (ready), a review that turned the
    # verdict (stopped), a newer session's candidate (stale), or stopping it.
    ImprovementStatus.READY: frozenset(
        {
            ImprovementStatus.READY,
            ImprovementStatus.RUNNING,
            ImprovementStatus.STOPPED,
            ImprovementStatus.STALE,
            ImprovementStatus.CANCELLED,
            ImprovementStatus.ACCEPTED,
            ImprovementStatus.PUBLISHED,
            ImprovementStatus.REJECTED,
        }
    ),
    # Undoing an accepted suggestion puts it back in front of a person.
    ImprovementStatus.ACCEPTED: frozenset(
        {ImprovementStatus.READY, ImprovementStatus.PUBLISHED, ImprovementStatus.REJECTED}
    ),
    # Continued within its limits, a measured round chosen, discarded, or stopped for good.
    ImprovementStatus.STOPPED: frozenset(
        {
            ImprovementStatus.RUNNING,
            ImprovementStatus.READY,
            ImprovementStatus.STALE,
            ImprovementStatus.CANCELLED,
            ImprovementStatus.REJECTED,
        }
    ),
    # A failed step retried, or the session discarded.
    ImprovementStatus.FAILED: frozenset({ImprovementStatus.RUNNING, ImprovementStatus.REJECTED}),
    # Over, but what it suggested can still be discarded.
    ImprovementStatus.STALE: frozenset({ImprovementStatus.REJECTED}),
    ImprovementStatus.CANCELLED: frozenset({ImprovementStatus.REJECTED}),
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


def _wait(stage: ImprovementStage) -> Transition:
    return Transition(ImprovementStatus.WAITING, stage)


def after_classifying(
    status: JobStatus | None, *, agent_answers: int, missing_knowledge: int
) -> Transition | None:
    """Wait for a person to propose for what the agent got wrong, or stop on missing
    knowledge; `None` while sorting.

    Answers missing knowledge are grouped into topics for a person to draft the
    ones they want; a session drafts none. So a session with the agent's own
    faults waits for a person to take it on to a proposal, and one with only
    missing knowledge ends there. An answer that was not a problem goes to
    neither, and one whose cause stayed unknown is the agent's to look at. A sort
    that failed leaves every answer to the agent.
    """
    if not _ended(status):
        return None
    if agent_answers:
        return _wait(ImprovementStage.CLASSIFYING)
    if missing_knowledge:
        return _stop(ImprovementStage.CLASSIFYING, StopReason.KNOWLEDGE_ONLY)
    return _stop(ImprovementStage.CLASSIFYING, StopReason.NO_PROPOSAL)


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
    """Wait for a person to choose what to check, unless the policy left nothing."""
    if kept == 0:
        return _stop(ImprovementStage.FILTERING, StopReason.NO_PROPOSAL)
    return _wait(ImprovementStage.FILTERING)


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
    counts cases nothing could grade. `crashed` counts cases the agent itself
    crashed on: those are failures already, in the pass rates and the confirmed
    flips, and the count is kept only to show beside the verdict. `suite` is the
    named suite's verdict on the same check, or `None` when the session names no
    suite.
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
    held_out: int | None = None


def judge(result: CheckResult) -> ImprovementVerdict:
    """The verdict on a candidate. Anything not measured is inconclusive, never better.

    An automatic session needs a complete measurement before choosing its next
    candidate. A failed suite or confirmed regression decides once every case
    was measured. An ordinary suite may fail on partial evidence independently.
    """
    if result.incomplete or result.ungraded:
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
    fixed: int
    broken: int
    held_out: int

    @property
    def change(self) -> float:
        """What the attempt changed against its own baseline, as a share of its held-out
        questions: each attempt is measured on its own draw, so counts alone do not compare."""
        return (self.fixed - self.broken) / self.held_out if self.held_out else 0.0


def best_round(rounds: list[RoundResult]) -> int | None:
    """Prefer a measured improvement, then the larger change against its own baseline.

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
        key=lambda item: (order[item.verdict], item.change, -item.number),
        default=None,
    )
    return None if best is None else best.number


def no_progress(rounds: list[RoundResult]) -> StopReason | None:
    """Why another attempt is unlikely to add anything: the last two changed nothing, or
    neither could be told apart from the base. A hint for a person, never a stop."""
    if len(rounds) < 2:
        return None
    previous, latest = rounds[-2], rounds[-1]
    if previous.verdict == latest.verdict == ImprovementVerdict.NO_CHANGE:
        return StopReason.NO_CHANGE
    if previous.verdict == latest.verdict == ImprovementVerdict.INCONCLUSIVE:
        return StopReason.INCONCLUSIVE
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


NOISY_SPREAD_QUESTIONS = 2
"""Shared held-out questions today's version may move by between attempts before the test is
noise.

Today's version is the same in every attempt, so on the questions two attempts both
measure any movement is the grading, not the agent. A typical attempt fixes one or
two questions, and a check that wobbles by as many cannot tell that fix from chance.
"""

NOISY_SPREAD_POINTS = 0.15
"""The same wobble as a share of the shared pass rate, for a set small enough that two
questions is already a large share."""

NOISY_UNSTABLE_SHARE = 0.2
"""Share of held-out questions graded both ways without the agent changing that
makes the test noise: a fifth of the set is more than an attempt usually moves."""

MIN_SHARED_QUESTIONS = 5
"""Shared held-out questions below which two attempts' scores of today's version say nothing:
each attempt draws its own, so only the questions both measured compare."""

NOISE_EXAMPLES = 5
"""Unstable questions shown as examples; the counts cover the rest."""


@dataclass(frozen=True)
class CheckedCase:
    """One held-out question's grades in one attempt, the first answer then each re-ask."""

    case_id: UUID
    input: str
    baseline: tuple[bool | None, ...]
    candidate: tuple[bool | None, ...]


@dataclass(frozen=True)
class CheckedAttempt:
    """One measured attempt's check: every held-out question it graded."""

    number: int
    cases: tuple[CheckedCase, ...]


def _both_ways(grades: Sequence[bool | None]) -> bool:
    return len({grade for grade in grades if grade is not None}) > 1


def _first(case: CheckedCase) -> bool | None:
    return case.baseline[0] if case.baseline else None


def measurement_noise(attempts: Sequence[CheckedAttempt]) -> MeasurementNoise | None:
    """Whether the attempts' checks could tell a better version from a worse one.

    Nothing is asked again: the signal is read from what the checks stored. Within
    an attempt, re-asks graded both ways are the grading moving. Between attempts,
    each measured on its own draw of questions, only the questions they share
    compare: today's version scored differently on them is the grading too.
    """
    if not attempts:
        return None
    holders: dict[UUID, int] = {}
    for attempt in attempts:
        for case in attempt.cases:
            holders[case.case_id] = holders.get(case.case_id, 0) + 1
    held_out = len(holders)
    shared = {case_id for case_id, count in holders.items() if count >= 2}
    too_few_shared = len(shared) < MIN_SHARED_QUESTIONS
    within: set[UUID] = set()
    by_attempt = []
    for attempt in attempts:
        baseline = {case.case_id for case in attempt.cases if _both_ways(case.baseline)}
        candidate = {case.case_id for case in attempt.cases if _both_ways(case.candidate)}
        within |= baseline | candidate
        by_attempt.append(
            AttemptNoise(
                number=attempt.number,
                baseline_unstable=len(baseline),
                candidate_unstable=len(candidate),
            )
        )
    between: set[UUID] = set()
    low = high = None
    spread: int | None = None
    if not too_few_shared:
        first_grades: dict[UUID, set[bool]] = {}
        passed: list[int] = []
        rates: list[float] = []
        for attempt in attempts:
            graded = [
                (case.case_id, grade)
                for case in attempt.cases
                if case.case_id in shared and (grade := _first(case)) is not None
            ]
            for case_id, grade in graded:
                first_grades.setdefault(case_id, set()).add(grade)
            if graded:
                hits = sum(grade for _, grade in graded)
                passed.append(hits)
                rates.append(hits / len(graded))
        between = {case_id for case_id, grades in first_grades.items() if len(grades) > 1}
        if rates:
            low, high = min(rates), max(rates)
            spread = max(passed) - min(passed)
    unstable = within | between
    wobble = round(high - low, 6) if low is not None and high is not None else 0.0
    noisy = (held_out > 0 and len(unstable) / held_out >= NOISY_UNSTABLE_SHARE) or (
        spread is not None and (spread >= NOISY_SPREAD_QUESTIONS or wobble >= NOISY_SPREAD_POINTS)
    )
    shown: list[UUID] = []
    for attempt in attempts:
        for case in attempt.cases:
            if case.case_id in unstable and case.case_id not in shown:
                shown.append(case.case_id)
    examples = [
        NoisyQuestion(
            case_id=case_id,
            input=next(
                case.input
                for attempt in attempts
                for case in attempt.cases
                if case.case_id == case_id
            ),
            attempts=[
                NoisyAttempt(
                    number=attempt.number,
                    baseline=list(case.baseline),
                    candidate=list(case.candidate),
                )
                for attempt in attempts
                for case in attempt.cases
                if case.case_id == case_id
            ],
        )
        for case_id in shown[:NOISE_EXAMPLES]
    ]
    return MeasurementNoise(
        noisy=noisy,
        held_out=held_out,
        within=len(within),
        shared=len(shared),
        between=None if too_few_shared else len(between),
        too_few_shared=too_few_shared,
        baseline_low=low,
        baseline_high=high,
        baseline_spread=spread,
        unstable=len(unstable),
        by_attempt=by_attempt,
        examples=examples,
    )
