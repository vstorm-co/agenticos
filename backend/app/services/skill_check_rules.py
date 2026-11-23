"""The rule a skill change is judged by, with no database and no model.

**One agent.** Each stage of an agent's check is a paired eval run, the stored
text against the candidate, compared on its held-out questions. The agent is
judged once, on its stages' held-out questions taken together, so the minimum a
result needs applies to the agent rather than to each stage, though a
regression one stage confirmed completely on its own decides beside a stage
that measured nothing. The agent improvement verdict reads that the same way
here: a confirmed regression is
`worse`; confirmed fixes and a pass rate that did not drop are `better`; anything
not measured is `unknown`. With no question flipped, a criterion its re-asks
confirmed better is `criteria_better` and one confirmed worse `criteria_worse`;
neither moves the change's own verdict, which stays about whole questions.
Flips its re-asks could not confirm make it
`within_noise` - the check saw a difference it cannot tell from the grading
moving; a better agent with such flips stays better, and its row is marked
noisy. An inconclusive agent is not asked again: it is `unknown`, and a person
checks the change again.

**The change.** It passes when no agent is worse and at least one is better.
`within_noise` warns and never blocks. An agent that could not be checked is
`unknown`, and a person acknowledges it before applying - also when no agent
could be.

**What a person may do.** On main, a change that made an agent worse may still be
applied with that agent pinned to the version it has now, and any change may be
made a fork, whatever its result: the person picks which agents move onto it. On a
fork neither exists: a pin names a main version and a fork never starts from
another fork.

**The agent's own questions in a quick check** are picked without a model: of the
questions whose answers loaded the skill, the ones sharing most words with the
lines the change touches, then the newest, then by id.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.db.models.improvement import ImprovementVerdict
from app.db.models.skill_check import AgentState, CheckOutcome, CheckVerdict
from app.services.eval_comparison import (
    MIN_FAMILY_CASES,
    CriterionMove,
    FamilyMove,
    mcnemar_p,
)
from app.services.improvement_states import CheckResult, judge

SAMPLE_SIZE = 4
"""How many of an agent's own questions a quick check asks at least."""

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")

# Short on purpose: a stray domain word costs one point of overlap, a dropped rule
# word would hide the questions the change can break.
_STOP_TEXT = (
    "a an and are as at be but by can do does for from has have i if in is it its me my "
    "no not of on or our so that the their them then there they this to was we what when "
    "which who will with would you your"
)
_STOP_WORDS = frozenset(_STOP_TEXT.split())


@dataclass(frozen=True)
class StageResult:
    """One stage's paired eval run, as the rule reads it."""

    check: CheckResult
    fixed_unconfirmed: int
    regressions_unconfirmed: int
    compared: int


def stage_state(stage: StageResult) -> AgentState:
    """What one stage says about the agent."""
    verdict = judge(stage.check)
    if verdict is ImprovementVerdict.REGRESSION:
        return AgentState.WORSE
    if verdict is ImprovementVerdict.INCONCLUSIVE:
        return AgentState.UNKNOWN
    if verdict is ImprovementVerdict.BETTER:
        return AgentState.BETTER
    if verdict is ImprovementVerdict.CRITERIA_WORSE:
        return AgentState.CRITERIA_WORSE
    if verdict is ImprovementVerdict.CRITERIA_BETTER:
        return AgentState.CRITERIA_BETTER
    if stage.regressions_unconfirmed or stage.fixed_unconfirmed:
        return AgentState.WITHIN_NOISE
    return AgentState.NO_CHANGE


def noisy(stage: StageResult) -> bool:
    """Whether a stage saw flips its re-asks could not confirm, whatever it concluded."""
    return bool(stage.regressions_unconfirmed or stage.fixed_unconfirmed)


@dataclass(frozen=True)
class StageComparison:
    """One stage's paired eval run, its held-out questions compared with no minimum."""

    comparable: bool
    """It had a baseline, and nothing but its own size made it invalid."""
    gradable_holdout: int
    incomplete: int
    ungraded: int
    crashed: int
    regressions_confirmed: int
    fixed_confirmed: int
    regressions_unconfirmed: int
    fixed_unconfirmed: int
    compared: int
    candidate_pass_rate: float | None
    baseline_pass_rate: float | None
    criteria: tuple[CriterionMove, ...] = ()
    families: tuple[FamilyMove, ...] = ()


def _pooled_families(stages: Sequence[StageComparison], *, alpha: float) -> tuple[FamilyMove, ...]:
    """Each family's counts over every stage that graded it, settled again as one measurement."""
    by_family: dict[str, list[FamilyMove]] = {}
    for stage in stages:
        for move in stage.families:
            by_family.setdefault(move.family, []).append(move)
    pooled_moves = []
    for family, moves in sorted(by_family.items()):
        fixed = sum(move.fixed for move in moves)
        broken = sum(move.broken for move in moves)
        p = mcnemar_p(broken, fixed)
        pooled_moves.append(
            FamilyMove(
                family=family,
                criteria=tuple(sorted({name for move in moves for name in move.criteria})),
                cases=sum(move.cases for move in moves),
                baseline_passed=sum(move.baseline_passed for move in moves),
                candidate_passed=sum(move.candidate_passed for move in moves),
                fixed=fixed,
                broken=broken,
                fixed_confirmed=sum(move.fixed_confirmed for move in moves),
                broken_confirmed=sum(move.broken_confirmed for move in moves),
                p_value=p,
                settled=fixed + broken >= MIN_FAMILY_CASES and p < alpha,
            )
        )
    return tuple(pooled_moves)


def _pooled_criteria(stages: Sequence[StageComparison]) -> tuple[CriterionMove, ...]:
    """Each criterion's counts over every stage that graded it, as one measurement."""
    by_key: dict[tuple[str, str], list[CriterionMove]] = {}
    for stage in stages:
        for move in stage.criteria:
            by_key.setdefault((move.scorer, move.name), []).append(move)
    return tuple(
        CriterionMove(
            scorer=scorer,
            name=name,
            graded=sum(move.graded for move in moves),
            baseline_passed=sum(move.baseline_passed for move in moves),
            candidate_passed=sum(move.candidate_passed for move in moves),
            fixed_confirmed=sum(move.fixed_confirmed for move in moves),
            broken_confirmed=sum(move.broken_confirmed for move in moves),
            fixed_unconfirmed=sum(move.fixed_unconfirmed for move in moves),
            broken_unconfirmed=sum(move.broken_unconfirmed for move in moves),
        )
        for (scorer, name), moves in sorted(by_key.items())
    )


def pooled(stages: Sequence[StageComparison], *, minimum: int, alpha: float) -> StageResult:
    """An agent's result from its stages' held-out questions taken as one measurement.

    The minimum a result needs is the agent's, not each stage's: four sampled questions
    and ten of the skill's are fourteen. The pass rates are weighted by what each stage
    compared, and a confirmed regression in any stage is one in the whole.
    """
    weighted = [stage for stage in stages if stage.compared]

    def rate(read: Callable[[StageComparison], float | None]) -> float | None:
        rates = [(read(stage), stage.compared) for stage in weighted]
        if not rates or any(value is None for value, _ in rates):
            return None
        return sum(value * count for value, count in rates if value is not None) / sum(
            count for _, count in rates
        )

    return StageResult(
        check=CheckResult(
            comparable=bool(stages)
            and all(stage.comparable for stage in stages)
            and sum(stage.gradable_holdout for stage in stages) >= minimum,
            incomplete=sum(stage.incomplete for stage in stages),
            ungraded=sum(stage.ungraded for stage in stages),
            crashed=sum(stage.crashed for stage in stages),
            regressions_confirmed=sum(stage.regressions_confirmed for stage in stages),
            fixed_confirmed=sum(stage.fixed_confirmed for stage in stages),
            candidate_pass_rate=rate(lambda stage: stage.candidate_pass_rate),
            baseline_pass_rate=rate(lambda stage: stage.baseline_pass_rate),
            criteria=_pooled_criteria(stages),
            families=_pooled_families(stages, alpha=alpha),
        ),
        fixed_unconfirmed=sum(stage.fixed_unconfirmed for stage in stages),
        regressions_unconfirmed=sum(stage.regressions_unconfirmed for stage in stages),
        compared=sum(stage.compared for stage in stages),
    )


def agent_state(stages: Sequence[StageComparison], *, minimum: int, alpha: float) -> AgentState:
    """What an agent's stages say about it.

    A stage measured completely on its own that confirmed a regression makes the agent
    worse whatever the others say - one unmeasured beside it hides nothing it found.
    The held-out minimum does not apply to that: no agent may get confirmed worse, and
    a regression its re-asks reproduced blocks however few questions found it, since
    blocking errs on the safe side. Getting better still needs the minimum, so
    otherwise the stages' held-out questions are judged together.
    """
    if any(
        stage.comparable
        and not stage.incomplete
        and not stage.ungraded
        and stage.regressions_confirmed
        for stage in stages
    ):
        return AgentState.WORSE
    return stage_state(pooled(stages, minimum=minimum, alpha=alpha))


def too_few_questions(stages: Sequence[StageComparison], *, minimum: int) -> bool:
    """Whether the stages measured everything they asked, and asked fewer held-out
    questions than a result needs - the one thing that kept the agent unknown."""
    return (
        bool(stages)
        and all(
            stage.comparable and not stage.incomplete and not stage.ungraded and not stage.crashed
            for stage in stages
        )
        and sum(stage.gradable_holdout for stage in stages) < minimum
    )


def verdict(states: Iterable[AgentState]) -> CheckVerdict:
    """The rule over every agent of the line, hidden ones included.

    A line whose every agent is unknown needs a person to acknowledge that, as any
    unknown agent does.
    """
    seen = list(states)
    if AgentState.WORSE in seen:
        return CheckVerdict.BLOCKED
    if seen and all(state is AgentState.UNKNOWN for state in seen):
        return CheckVerdict.NEEDS_ACK
    if AgentState.BETTER not in seen:
        return CheckVerdict.NO_BETTER
    if AgentState.UNKNOWN in seen:
        return CheckVerdict.NEEDS_ACK
    return CheckVerdict.PASSED


def outcomes(result: CheckVerdict, *, fork: bool) -> list[CheckOutcome]:
    """What a person may do with a finished check, in the order the page offers them.

    A check on main may always become a fork, whatever its result: the person decides
    which agents move onto it, the helped ones unless they pick others or none.
    """
    forked = [] if fork else [CheckOutcome.FORK_FOR_HELPED]
    if result is CheckVerdict.BLOCKED:
        if fork:
            return [CheckOutcome.IMPROVE_FURTHER, CheckOutcome.DISCARD]
        return [
            CheckOutcome.IMPROVE_FURTHER,
            CheckOutcome.APPLY_AND_PIN,
            *forked,
            CheckOutcome.DISCARD,
        ]
    if result is CheckVerdict.NO_BETTER:
        return [CheckOutcome.IMPROVE_FURTHER, *forked, CheckOutcome.DISCARD]
    return [CheckOutcome.APPLY, CheckOutcome.IMPROVE_FURTHER, *forked, CheckOutcome.DISCARD]


def update_outcomes(result: CheckVerdict) -> list[CheckOutcome]:
    """What a pinned agent's update offers: moving it unless main's newest made it worse."""
    if result is CheckVerdict.BLOCKED:
        return [CheckOutcome.DISCARD]
    return [CheckOutcome.APPLY, CheckOutcome.DISCARD]


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in _STOP_WORDS}


def changed_words(before: str, after: str) -> set[str]:
    """The words of the lines one text has and the other does not."""
    old = {line.strip() for line in before.splitlines() if line.strip()}
    new = {line.strip() for line in after.splitlines() if line.strip()}
    return _words("\n".join(sorted(old ^ new)))


@dataclass(frozen=True)
class SampleCandidate:
    """A question of the agent's dataset whose newest answer loaded the skill."""

    case_id: UUID
    text: str
    answered_at: datetime


def sample(
    candidates: Sequence[SampleCandidate], changed: set[str], *, size: int = SAMPLE_SIZE
) -> list[UUID]:
    """The questions a quick check asks of one agent, most relevant to the change first.

    Ranked by the words a question shares with the changed lines, then the newest
    answer, then the case id; with nothing shared - a change to formatting alone -
    the newest decide.
    """
    ranked = sorted(
        candidates,
        key=lambda case: (
            -len(_words(case.text) & changed),
            -case.answered_at.timestamp(),
            str(case.case_id),
        ),
    )
    return [case.case_id for case in ranked[:size]]


def sample_size(skill_set_held_out: int, *, minimum: int) -> int:
    """How many of an agent's own questions a quick check asks: four, or as many as the
    agent's result needs beside the skill's held-out questions to reach the minimum."""
    return max(SAMPLE_SIZE, minimum - skill_set_held_out)


def total(amounts: Iterable[Decimal]) -> Decimal:
    """Money added up without a float in between."""
    return sum(amounts, Decimal(0))
