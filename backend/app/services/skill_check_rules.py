"""The rule a skill change is judged by, with no database and no model.

**One agent.** Each stage of an agent's check is a paired eval run, the stored
text against the candidate, and the agent improvement verdict reads it the same
way here: a confirmed regression is `worse`; confirmed fixes and a pass rate that
did not drop are `better`; anything not measured is `unknown`. A stage with
flips its re-asks could not confirm is `within_noise` - the check saw a
difference it cannot tell from the grading moving; a better stage with such
flips stays better, and its row is marked noisy. A worse stage makes the agent
worse; otherwise one better stage makes it better. An inconclusive stage is not
asked again: the agent is `unknown`, and a person checks the change again.

**The change.** It passes when no agent is worse and at least one is better.
`within_noise` warns and never blocks. An agent that could not be checked is
`unknown`, and a person acknowledges it before applying.

**What a person may do.** On main, a change that made an agent worse may still be
applied with that agent pinned to the version it has now, or made a fork for the
agents it helped. On a fork neither exists: a pin names a main version and a fork
never starts from another fork.

**The agent's own questions in a quick check** are picked without a model: of the
questions whose answers loaded the skill, the ones sharing most words with the
lines the change touches, then the newest, then by id.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.db.models.improvement import ImprovementVerdict
from app.db.models.skill_check import AgentState, CheckOutcome, CheckVerdict
from app.services.improvement_states import CheckResult, judge

SAMPLE_SIZE = 4
"""How many of an agent's own questions a quick check asks."""

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
    if stage.regressions_unconfirmed or stage.fixed_unconfirmed:
        return AgentState.WITHIN_NOISE
    return AgentState.NO_CHANGE


def noisy(stage: StageResult) -> bool:
    """Whether a stage saw flips its re-asks could not confirm, whatever it concluded."""
    return bool(stage.regressions_unconfirmed or stage.fixed_unconfirmed)


def combined(states: Sequence[AgentState]) -> AgentState:
    """An agent's result from its stages.

    A worse stage decides even beside an unmeasured one: a confirmed regression is
    a regression whatever else was or was not seen. Otherwise an unmeasured stage
    leaves the agent unknown, a better one makes it better - a stage within noise
    beside it stays a warning on the row - and only then does noise show.
    """
    for state in (AgentState.WORSE, AgentState.UNKNOWN, AgentState.BETTER):
        if state in states:
            return state
    if AgentState.WITHIN_NOISE in states:
        return AgentState.WITHIN_NOISE
    return AgentState.NO_CHANGE if states else AgentState.UNKNOWN


def verdict(states: Iterable[AgentState]) -> CheckVerdict:
    """The rule over every agent of the line, hidden ones included."""
    seen = list(states)
    if AgentState.WORSE in seen:
        return CheckVerdict.BLOCKED
    if AgentState.BETTER not in seen:
        return CheckVerdict.NO_BETTER
    if AgentState.UNKNOWN in seen:
        return CheckVerdict.NEEDS_ACK
    return CheckVerdict.PASSED


def outcomes(result: CheckVerdict, *, fork: bool) -> list[CheckOutcome]:
    """What a person may do with a finished check, in the order the page offers them."""
    if result is CheckVerdict.BLOCKED:
        if fork:
            return [CheckOutcome.IMPROVE_FURTHER, CheckOutcome.DISCARD]
        return [
            CheckOutcome.IMPROVE_FURTHER,
            CheckOutcome.APPLY_AND_PIN,
            CheckOutcome.FORK_FOR_HELPED,
            CheckOutcome.DISCARD,
        ]
    if result is CheckVerdict.NO_BETTER:
        return [CheckOutcome.IMPROVE_FURTHER, CheckOutcome.DISCARD]
    return [CheckOutcome.APPLY, CheckOutcome.IMPROVE_FURTHER, CheckOutcome.DISCARD]


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


def total(amounts: Iterable[Decimal]) -> Decimal:
    """Money added up without a float in between."""
    return sum(amounts, Decimal(0))
