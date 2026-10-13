"""The scorers themselves: what each concludes about one answer to one case.

Pure functions over an answer and a case - no database, no model. The judge's
half is here too, short of calling it: which criteria it is asked, the prompt
that asks them, and how its grades become results. `ScoringService` runs the
judge and keeps what these return.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from pydantic import BaseModel, JsonValue
from pydantic import ValidationError as PydanticValidationError

from app.schemas.scoring import (
    CHECK,
    CeilingCheck,
    DatasetScoring,
    JsonSchemaCheck,
    JudgeCheck,
    ScorerKind,
    ScorerResult,
    TextCheck,
)

# A pattern is bounded where it is written; bounding the text it reads keeps one
# match's cost bounded whatever the agent said.
MAX_MATCH_TEXT = 100_000
_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?|\n?```\s*$")


@dataclass(frozen=True)
class ScoredCall:
    """One tool call the agent made, in the order it made it.

    `blocked` is a write an isolated run stopped before it reached anything. It
    still counts as a call the agent made: choosing to make it is what a
    trajectory is about.
    """

    tool: str
    args: Mapping[str, Any]
    blocked: bool = False


@dataclass(frozen=True)
class ScoredAnswer:
    """What a run produced, as the scorers read it.

    Attributes:
        text: The final answer.
        calls: Every tool call, in order.
        cost_usd: What the run cost, when known.
        latency_ms: How long it took, when it ended.
        run_id: The recorded run, when there is one.
    """

    text: str
    calls: tuple[ScoredCall, ...] = ()
    cost_usd: Decimal | None = None
    latency_ms: int | None = None
    run_id: UUID | None = None


@dataclass(frozen=True)
class CaseView:
    """The parts of a case revision the scorers read."""

    input: str
    history: Sequence[Mapping[str, Any]]
    reference_answer: str | None
    counter_example: str | None
    expected_tool_calls: Sequence[Mapping[str, Any]]
    order_mode: str
    checks: Sequence[Mapping[str, Any]]


class _NoValue(Exception):
    """The answer has nothing a rule can read where it looks."""


def _json(text: str) -> JsonValue:
    try:
        return json.loads(_FENCE.sub("", text.strip()).strip())
    except json.JSONDecodeError as exc:
        raise _NoValue("The answer is not JSON") from exc


def _at(data: JsonValue, path: str) -> JsonValue:
    value = data
    for step in path.split("."):
        if isinstance(value, dict) and step in value:
            value = value[step]
        elif isinstance(value, list) and step.isdigit() and int(step) < len(value):
            value = value[int(step)]
        else:
            raise _NoValue(f"The answer has nothing at `{path}`")
    return value


def _value(answer: ScoredAnswer, path: str | None) -> JsonValue:
    data = _json(answer.text)
    return data if path is None else _at(data, path)


def _text(answer: ScoredAnswer, path: str | None) -> str:
    if path is None:
        return answer.text[:MAX_MATCH_TEXT]
    value = _value(answer, path)
    return (value if isinstance(value, str) else json.dumps(value))[:MAX_MATCH_TEXT]


def _result(
    name: str,
    *,
    passed: bool,
    reason: str,
    required: bool,
    scorer: ScorerKind = "check",
    score: float | None = None,
) -> ScorerResult:
    return ScorerResult(
        scorer=scorer,
        name=name,
        required=required,
        status="pass" if passed else "fail",
        score=(1.0 if passed else 0.0) if score is None else score,
        reason=reason,
    )


def _text_check(check: TextCheck, answer: ScoredAnswer, *, required: bool) -> ScorerResult:
    where = f" at `{check.path}`" if check.path else ""
    name = f"{check.type} {check.value!r}{where}"
    try:
        subject = _text(answer, check.path)
    except _NoValue as exc:
        return _result(name, passed=False, reason=str(exc), required=required)
    flags = 0 if check.case_sensitive else re.IGNORECASE
    haystack, needle = (
        (subject, check.value)
        if check.case_sensitive
        else (subject.casefold(), check.value.casefold())
    )
    if check.type == "contains":
        passed = needle in haystack
        reason = "Contains it" if passed else "Does not contain it"
    elif check.type == "not_contains":
        passed = needle not in haystack
        reason = "Does not contain it" if passed else "Contains it"
    elif check.type == "equals":
        passed = haystack.strip() == needle.strip()
        reason = "Equal" if passed else "Not equal"
    else:
        passed = re.search(check.value, subject, flags) is not None
        reason = "Matches" if passed else "Does not match"
    return _result(name, passed=passed, reason=reason, required=required)


def _schema_check(check: JsonSchemaCheck, answer: ScoredAnswer, *, required: bool) -> ScorerResult:
    name = "json_schema" + (f" at `{check.path}`" if check.path else "")
    try:
        value = _value(answer, check.path)
    except _NoValue as exc:
        return _result(name, passed=False, reason=str(exc), required=required)
    error = best_match(Draft202012Validator(check.json_schema).iter_errors(value))
    if error is None:
        return _result(name, passed=True, reason="Matches the schema", required=required)
    where = "/".join(str(step) for step in error.absolute_path) or "the answer"
    return _result(name, passed=False, reason=f"{where}: {error.message}"[:500], required=required)


def _ceiling_check(check: CeilingCheck, answer: ScoredAnswer, *, required: bool) -> ScorerResult:
    if check.type == "max_cost_usd":
        name, measured, unit = f"cost at most ${check.value:g}", answer.cost_usd, "$"
    else:
        name, measured, unit = f"latency at most {check.value:g} ms", answer.latency_ms, "ms"
    if measured is None:
        return ScorerResult(
            scorer="check",
            name=name,
            required=required,
            status="error",
            reason="The run did not record it",
            reason_code="not_measured",
        )
    shown = f"${float(measured):.4f}" if unit == "$" else f"{measured} ms"
    passed = float(measured) <= check.value
    return _result(name, passed=passed, reason=f"Took {shown}", required=required)


def run_checks(
    checks: Sequence[Mapping[str, Any]], answer: ScoredAnswer, *, required: bool
) -> tuple[list[ScorerResult], list[JudgeCheck]]:
    """Every rule-based check, and the judge criteria among them to grade separately.

    A stored check this build cannot read is reported as an error rather than
    refused: it was valid when it was written, and the rest still score.
    """
    results: list[ScorerResult] = []
    judged: list[JudgeCheck] = []
    for raw in checks:
        try:
            check = CHECK.validate_python(raw)
        except PydanticValidationError:
            results.append(
                ScorerResult(
                    scorer="check",
                    name=str(raw.get("type", "check")),
                    required=required,
                    status="error",
                    reason="This check cannot be read; edit the case to fix it",
                    reason_code="unknown_check",
                )
            )
            continue
        if isinstance(check, JudgeCheck):
            judged.append(check)
        elif isinstance(check, TextCheck):
            results.append(_text_check(check, answer, required=required))
        elif isinstance(check, JsonSchemaCheck):
            results.append(_schema_check(check, answer, required=required))
        else:
            results.append(_ceiling_check(check, answer, required=required))
    return results, judged


def _matches(expected: Mapping[str, Any], call: ScoredCall) -> bool:
    if call.tool != expected["tool"]:
        return False
    return all(
        key in call.args and call.args[key] == value
        for key, value in expected.get("args", {}).items()
    )


def _named(calls: Sequence[Mapping[str, Any]] | Sequence[ScoredCall]) -> str:
    names = [call.tool if isinstance(call, ScoredCall) else str(call["tool"]) for call in calls]
    return ", ".join(names)


def score_trajectory(
    expected: Sequence[Mapping[str, Any]],
    calls: Sequence[ScoredCall],
    *,
    order_mode: str,
    required: bool,
) -> ScorerResult | None:
    """The agent's calls against the expected ones, or nothing when none are expected.

    `any`: every expected call happened, in any order, others allowed. `in_order`:
    they happened in the listed order, others allowed between. `exact`: exactly
    those calls in that order and nothing else. A call matches on its tool and on
    every argument the expectation names.
    """
    if not expected:
        return None
    pairing = _pair(expected, calls)
    missing = [item for i, item in enumerate(expected) if i not in pairing]
    used = set(pairing.values())
    extra = [call for i, call in enumerate(calls) if i not in used]
    found = len(pairing)

    problems: list[str] = []
    if missing:
        problems.append(f"Missing: {_named(missing)}")
    if order_mode == "exact" and extra:
        problems.append(f"Not expected: {_named(extra)}")
    if not missing and order_mode in ("in_order", "exact") and not _in_order(expected, calls):
        problems.append("Called in a different order")

    blocked = [call for call in calls if call.blocked]
    note = f" ({_named(blocked)} blocked, not executed)" if blocked else ""
    if problems:
        return ScorerResult(
            scorer="trajectory",
            name=f"tool calls ({order_mode})",
            required=required,
            status="fail",
            score=found / len(expected),
            reason="; ".join(problems) + note,
        )
    return ScorerResult(
        scorer="trajectory",
        name=f"tool calls ({order_mode})",
        required=required,
        status="pass",
        score=1.0,
        reason=f"Called {_named(expected)}{note}",
    )


def _pair(expected: Sequence[Mapping[str, Any]], calls: Sequence[ScoredCall]) -> dict[int, int]:
    """The most expected calls that can each be matched to a distinct call made.

    A maximum bipartite matching rather than first-come: an expectation naming
    no arguments must not take the one call a more specific expectation needed.
    """
    pairing: dict[int, int] = {}
    taken: dict[int, int] = {}

    def place(item: int, seen: set[int]) -> bool:
        for index, call in enumerate(calls):
            if index in seen or not _matches(expected[item], call):
                continue
            seen.add(index)
            holder = taken.get(index)
            if holder is None or place(holder, seen):
                taken[index] = item
                pairing[item] = index
                return True
        return False

    for item in range(len(expected)):
        place(item, set())
    return pairing


def _in_order(expected: Sequence[Mapping[str, Any]], calls: Sequence[ScoredCall]) -> bool:
    position = 0
    for item in expected:
        index = next((i for i in range(position, len(calls)) if _matches(item, calls[i])), None)
        if index is None:
            return False
        position = index + 1
    return True


def case_passed(results: Sequence[ScorerResult]) -> bool | None:
    """Whether a case passed: every required scorer passed.

    A required scorer that failed or errored fails it. One that was skipped - the
    judge refused, switched off, out of budget - leaves it unscored (`None`), never
    passed: a gate reading the result must not count what nobody checked. Nothing
    required to score leaves it unscored too.
    """
    required = [result for result in results if result.required]
    if any(result.status in ("fail", "error") for result in required):
        return False
    if not required or any(result.status == "skipped" for result in required):
        return None
    return True


@dataclass(frozen=True)
class JudgeCriterion:
    """One thing the judge is asked to grade, and where it came from."""

    id: str
    scorer: ScorerKind
    name: str
    description: str
    required: bool


class JudgeGrade(BaseModel):
    id: str
    score: int
    reason: str


class JudgeVerdict(BaseModel):
    """The judge's answer: one grade per criterion id."""

    grades: list[JudgeGrade]


REFERENCE_CRITERION = (
    "The answer agrees with the reference answer on every fact the question turns on. "
    "Wording may differ; a missing or contradicted fact does not."
)


def judge_criteria(
    case: CaseView, scoring: DatasetScoring, judged: Sequence[JudgeCheck]
) -> list[JudgeCriterion]:
    """What the judge grades for this case: the rubric, the reference, the case's own."""
    criteria = [
        JudgeCriterion(
            id=f"r{index}",
            scorer="judge",
            name=criterion.name,
            description=criterion.description,
            required=criterion.required,
        )
        for index, criterion in enumerate(scoring.judge.criteria, start=1)
        if scoring.judge.enabled
    ]
    if scoring.reference.enabled and case.reference_answer:
        criteria.append(
            JudgeCriterion(
                id="ref",
                scorer="reference",
                name="reference answer",
                description=REFERENCE_CRITERION,
                required=scoring.reference.required,
            )
        )
    criteria.extend(
        JudgeCriterion(
            id=f"c{index}",
            scorer="judge",
            name=check.criterion[:80],
            description=check.criterion,
            required=scoring.checks.required,
        )
        for index, check in enumerate(judged, start=1)
    )
    return criteria


def judge_prompt(
    case: CaseView, answer: ScoredAnswer, criteria: Sequence[JudgeCriterion], *, scale_max: int
) -> str:
    """The task the judge is handed: the case, the answer and the criteria by id."""
    parts = []
    if case.history:
        turns = "\n".join(f"{turn['role']}: {turn['content']}" for turn in case.history)
        parts.append(f"<conversation_so_far>\n{turns}\n</conversation_so_far>")
    parts.append(f"<question>\n{case.input}\n</question>")
    if any(criterion.scorer == "reference" for criterion in criteria):
        parts.append(f"<reference_answer>\n{case.reference_answer}\n</reference_answer>")
    if case.counter_example:
        parts.append(f"<counter_example>\n{case.counter_example}\n</counter_example>")
    parts.append(f"<answer>\n{answer.text[:MAX_MATCH_TEXT]}\n</answer>")
    listed = "\n".join(f"- {c.id} ({c.name}): {c.description}" for c in criteria)
    parts.append(
        f"Grade the answer on each criterion below, from 1 (does not meet it at all) to "
        f"{scale_max} (fully meets it). Give exactly one grade per criterion id.\n{listed}"
    )
    return "\n\n".join(parts)


def graded(
    criteria: Sequence[JudgeCriterion],
    verdict: JudgeVerdict,
    *,
    scale_max: int,
    pass_at: int,
    run_id: UUID,
) -> list[ScorerResult]:
    """The judge's grades as results; a criterion it skipped or misgraded is an error."""
    grades = {grade.id: grade for grade in verdict.grades}
    results = []
    for criterion in criteria:
        grade = grades.get(criterion.id)
        if grade is None or not 1 <= grade.score <= scale_max:
            results.append(
                ScorerResult(
                    scorer=criterion.scorer,
                    name=criterion.name,
                    required=criterion.required,
                    status="error",
                    reason="The judge gave no grade on the scale for this criterion",
                    reason_code="judge_ungraded",
                    judge_run_id=run_id,
                )
            )
            continue
        results.append(
            ScorerResult(
                scorer=criterion.scorer,
                name=criterion.name,
                required=criterion.required,
                status="pass" if grade.score >= pass_at else "fail",
                score=grade.score / scale_max,
                reason=f"{grade.score}/{scale_max}: {grade.reason}"[:2000],
                judge_run_id=run_id,
            )
        )
    return results


def not_graded(
    criteria: Sequence[JudgeCriterion],
    *,
    skipped: bool,
    code: str,
    reason: str,
    run_id: UUID | None = None,
) -> list[ScorerResult]:
    """Every criterion the judge could not grade, with why."""
    return [
        ScorerResult(
            scorer=criterion.scorer,
            name=criterion.name,
            required=criterion.required,
            status="skipped" if skipped else "error",
            reason=reason,
            reason_code=code,
            judge_run_id=run_id,
        )
        for criterion in criteria
    ]
