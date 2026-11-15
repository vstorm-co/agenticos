"""The scorers themselves: what each concludes about one answer to one case.

Pure functions over an answer and a case - no database, no model. The judge's
half is here too, short of calling it: which criteria it is asked, the prompt
that asks them, and how its grades become results. `ScoringService` runs the
judge and keeps what these return.
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import regex
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from pydantic import BaseModel, Field, JsonValue, field_validator
from pydantic import ValidationError as PydanticValidationError
from referencing.exceptions import Unresolvable

from app.schemas.scoring import (
    CHECK,
    CeilingCheck,
    DatasetScoring,
    JsonSchemaCheck,
    JudgeCheck,
    LengthCheck,
    ScorerKind,
    ScorerResult,
    TextCheck,
)
from app.services.authoring_hunks import evened, mentioned

MAX_QUOTES = 12
MAX_QUOTE = 600
MAX_RULE = 300
MAX_REASON = 2000
_QUOTE_SHOWN = 80
_QUOTE_EDGES = " '\"\u2018\u2019\u201c\u201d\u201e\u00ab\u00bb"
_QUOTE_END = ".,;:!?\u2026 "

MAX_MATCH_TEXT = 100_000
# A pattern is a person's input and backtracking is exponential in the text it
# reads, so a match runs under a deadline rather than a length cap alone.
PATTERN_SECONDS = 0.1
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
        agent_id: The agent that answered, when it is known.
    """

    text: str
    calls: tuple[ScoredCall, ...] = ()
    cost_usd: Decimal | None = None
    latency_ms: int | None = None
    run_id: UUID | None = None
    agent_id: UUID | None = None


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
    note: str | None = None
    tags: Sequence[str] = ()


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
    flags = 0 if check.case_sensitive else regex.IGNORECASE
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
        try:
            passed = regex.search(check.value, subject, flags, timeout=PATTERN_SECONDS) is not None
        except TimeoutError:
            return ScorerResult(
                scorer="check",
                name=name,
                required=required,
                status="error",
                reason="The pattern took too long on this answer; simplify it",
                reason_code="pattern_timeout",
            )
        reason = "Matches" if passed else "Does not match"
    return _result(name, passed=passed, reason=reason, required=required)


def _schema_check(check: JsonSchemaCheck, answer: ScoredAnswer, *, required: bool) -> ScorerResult:
    name = "json_schema" + (f" at `{check.path}`" if check.path else "")
    try:
        value = _value(answer, check.path)
    except _NoValue as exc:
        return _result(name, passed=False, reason=str(exc), required=required)
    try:
        error = best_match(Draft202012Validator(check.json_schema).iter_errors(value))
    except Unresolvable:
        return ScorerResult(
            scorer="check",
            name=name,
            required=required,
            status="error",
            reason="The schema refers to a part of itself that does not exist",
            reason_code="schema_unresolvable",
        )
    if error is None:
        return _result(name, passed=True, reason="Matches the schema", required=required)
    where = "/".join(str(step) for step in error.absolute_path) or "the answer"
    return _result(name, passed=False, reason=f"{where}: {error.message}"[:500], required=required)


def _length_check(check: LengthCheck, answer: ScoredAnswer, *, required: bool) -> ScorerResult:
    bounds = " to ".join(
        bound
        for bound in (
            None if check.min is None else f"at least {check.min}",
            None if check.max is None else f"at most {check.max}",
        )
        if bound
    )
    where = f" at `{check.path}`" if check.path else ""
    name = f"{bounds} {check.unit}{where}"
    try:
        value = answer.text if check.path is None else _value(answer, check.path)
    except _NoValue as exc:
        return _result(name, passed=False, reason=str(exc), required=required)
    subject = value if isinstance(value, str) else json.dumps(value)
    measured = len(subject.split()) if check.unit == "words" else len(subject)
    passed = (check.min is None or measured >= check.min) and (
        check.max is None or measured <= check.max
    )
    return _result(name, passed=passed, reason=f"{measured} {check.unit}", required=required)


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
        elif isinstance(check, LengthCheck):
            results.append(_length_check(check, answer, required=required))
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

    A required scorer that failed fails it. One that could not reach a verdict -
    it errored, or was skipped because the judge was refused, switched off or out
    of budget - leaves it unscored (`None`), never passed and never failed: a gate
    reading the result must not count what nobody checked, either way. Nothing
    required to score leaves it unscored too.
    """
    required = [result for result in results if result.required]
    if any(result.status == "fail" for result in required):
        return False
    if not required or any(result.status in ("skipped", "error") for result in required):
        return None
    return True


def judge_verdict(results: Sequence[ScorerResult]) -> bool | None:
    """What the judge alone concluded: `case_passed` over its own results.

    The rubric and the reference answer are what a judge's run grades; the
    checks and the expected tool calls beside them are not its verdict.
    """
    return case_passed([result for result in results if result.scorer in ("judge", "reference")])


@dataclass(frozen=True)
class JudgeCriterion:
    """One thing the judge is asked to grade, and where it came from."""

    id: str
    scorer: ScorerKind
    name: str
    description: str
    required: bool


class JudgeGrade(BaseModel):
    """One criterion's grade.

    `quotes` are the passages of the answer the grade rests on, word for word.
    Each is looked for in the answer; one that is not there is kept beside the
    grade, and the grade stands. An empty or overlong quote is dropped and the
    list cut to its limit, and an overlong rule is cut, rather than refusing the
    whole verdict. `rule` is the rule the grade follows from - a
    line of a policy the judge was given, or the part of the criterion it turns on.
    """

    id: str
    score: int
    reason: str
    rule: str = Field(default="", description=f"At most {MAX_RULE} characters")
    quotes: list[str] = Field(
        default_factory=list,
        description=f"At most {MAX_QUOTES} passages of at most {MAX_QUOTE} characters each",
    )

    # Only the criterion id and the grade must be right for a grade to stand: a
    # judge that overruns a limit on what backs it loses the overrun, not the grade.
    @field_validator("rule", mode="before")
    @classmethod
    def _rule_cut(cls, value: object) -> str:
        return value[:MAX_RULE] if isinstance(value, str) else ""

    @field_validator("quotes", mode="before")
    @classmethod
    def _quotes_kept(cls, value: object) -> list[str]:
        given = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        kept = [q for q in given if isinstance(q, str) and q.strip() and len(q) <= MAX_QUOTE]
        return kept[:MAX_QUOTES]


class JudgeVerdict(BaseModel):
    """The judge's answer: one grade per criterion id."""

    grades: list[JudgeGrade]


# Bumped whenever what `judge_prompt` hands the judge changes, so a score graded
# from one prompt is never compared as like for like with one graded from another.
JUDGE_PROMPT_VERSION = 4

COUNTER_ID = "counter"
COUNTER_CRITERION = (
    "The answer does not repeat the mistake of the counter-example, a known bad answer "
    "to this question."
)
_MAX_CALLS_SHOWN = 50
_MAX_ARGS_SHOWN = 1_000
# A reason this much made of the criterion's own words says nothing about the answer.
_RESTATED_SHARE = 0.8
# Fewer words than this, an answer inside the counter-example ("No.") is a
# common phrase rather than a copy of it.
_COPY_MIN_WORDS = 3

REFERENCE_CRITERION = (
    "The answer agrees with the reference answer on every fact the question turns on. "
    "Wording may differ; a missing or contradicted fact does not."
)


def judge_criteria(
    case: CaseView, scoring: DatasetScoring, judged: Sequence[JudgeCheck]
) -> list[JudgeCriterion]:
    """What the judge grades for this case: the rubric, the reference, the case's own.

    A case with a counter-example is always asked not to repeat it, and must
    not, once the judge grades the dataset at all: a known bad answer is the
    most direct thing a case can say about its answer.
    """
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
        and (not criterion.tags or set(criterion.tags).intersection(case.tags))
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
    if case.counter_example and (scoring.judge.enabled or scoring.reference.enabled):
        criteria.append(
            JudgeCriterion(
                id=COUNTER_ID,
                scorer="reference",
                name="counter-example",
                description=COUNTER_CRITERION,
                required=True,
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


def _call_line(number: int, call: ScoredCall) -> str:
    args = json.dumps(call.args, ensure_ascii=False, default=str)
    if len(args) > _MAX_ARGS_SHOWN:
        args = f"{args[:_MAX_ARGS_SHOWN]}…"
    done = "blocked before it ran" if call.blocked else "ran"
    return f"{number}. {call.tool} {args} ({done})"


def _tool_calls(answer: ScoredAnswer) -> str:
    if not answer.calls:
        return "<tool_calls>\nThe agent called no tools.\n</tool_calls>"
    lines = [
        _call_line(number, call)
        for number, call in enumerate(answer.calls[:_MAX_CALLS_SHOWN], start=1)
    ]
    if len(answer.calls) > _MAX_CALLS_SHOWN:
        lines.append(f"… and {len(answer.calls) - _MAX_CALLS_SHOWN} more")
    return "<tool_calls>\n" + "\n".join(lines) + "\n</tool_calls>"


def judge_prompt(
    case: CaseView, answer: ScoredAnswer, criteria: Sequence[JudgeCriterion], *, scale_max: int
) -> str:
    """The task the judge is handed: the case, the answer, the agent's calls, the criteria.

    What changes here changes what every judge is asked, so it bumps
    `JUDGE_PROMPT_VERSION`.
    """
    parts = []
    if case.note:
        parts.append(f"<why_this_case_exists>\n{case.note}\n</why_this_case_exists>")
    if case.history:
        turns = "\n".join(f"{turn['role']}: {turn['content']}" for turn in case.history)
        parts.append(f"<conversation_so_far>\n{turns}\n</conversation_so_far>")
    parts.append(f"<question>\n{case.input}\n</question>")
    if any(criterion.scorer == "reference" and criterion.id == "ref" for criterion in criteria):
        parts.append(f"<reference_answer>\n{case.reference_answer}\n</reference_answer>")
    if case.counter_example:
        parts.append(f"<counter_example>\n{case.counter_example}\n</counter_example>")
    parts.append(_tool_calls(answer))
    parts.append(f"<answer>\n{answer.text[:MAX_MATCH_TEXT]}\n</answer>")
    listed = "\n".join(f"- {c.id} ({c.name}): {c.description}" for c in criteria)
    parts.append(
        f"Grade the answer on each criterion below, from 1 (does not meet it at all) to "
        f"{scale_max} (fully meets it). Give exactly one grade per criterion id. The tool "
        f"calls are what the agent did before answering; grade them only where a criterion "
        f"asks about them. For every criterion, copy word for word into the grade's quotes "
        f"the short passage of the answer the grade rests on, name in its rule the rule the "
        f"grade follows from - a line of the policy you were given, or the part of the "
        f"criterion it turns on - and say in its reason what in this answer decided it. Do "
        f"not restate the criterion. A top grade with nothing quoted from the answer is "
        f"treated as unverified.\n{listed}"
    )
    if any(criterion.id == COUNTER_ID for criterion in criteria):
        parts.append(
            f"For {COUNTER_ID}, quote what sets the answer apart from the counter-example: a "
            "passage of the answer the counter-example does not say. If the counter-example "
            'is "Your order shipped today." and the answer is "Your order has not shipped '
            'yet; it leaves on Friday.", quote "has not shipped yet". Never quote a passage '
            "the two share."
        )
    return "\n\n".join(parts)


def rubric_hash(criteria: Sequence[JudgeCriterion], *, scale_max: int) -> str:
    """A fingerprint of what the judge was asked: every criterion it graded, and the scale."""
    asked = {
        "scale_max": scale_max,
        "criteria": [[c.id, c.name, c.description] for c in criteria],
    }
    canonical = json.dumps(asked, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def holds(answer: str, quote: str) -> bool:
    """Whether the answer, already put through :func:`evened`, says the quote word
    for word.

    Compared as loosely as an authoring anchor is - spacing, and the style of
    quotation marks, apostrophes and dashes aside - and without the quote's own
    surrounding quotation marks and final punctuation: a judge quoting a clause
    ends it with a full stop where the answer goes on. The answer is evened once
    by the caller: a verdict carries a dozen quotes for each of many criteria.
    """
    said = quote.strip(_QUOTE_EDGES).rstrip(_QUOTE_END).rstrip(_QUOTE_EDGES)
    return mentioned(answer, said)


def _unverified(quotes: Sequence[str], answer: str) -> list[str]:
    """The quotes the evened answer does not hold, each cut to what a reader needs."""
    return [
        quote if len(quote) <= _QUOTE_SHOWN else f"{quote[:_QUOTE_SHOWN]}…"
        for quote in quotes
        if not holds(answer, quote)
    ]


def _words(text: str) -> list[str]:
    """The words of a text that carry meaning: longer than three letters, case aside."""
    return [word for word in re.findall(r"\w+", text.casefold()) if len(word) > 3]


def restates(reason: str, criterion: str) -> bool:
    """Whether a reason is mostly the criterion's own words rather than the answer's.

    Measured by the share of the reason's words the criterion also holds, so a
    criterion copied with one word swapped - "(approve, deny or need more info)"
    for "(deny)" - counts as copied. A reason with no word long enough to count
    says nothing either way and is left to stand.
    """
    said = _words(reason)
    if not said:
        return False
    asked = set(_words(criterion))
    return sum(word in asked for word in said) / len(said) >= _RESTATED_SHARE


def _sequence(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def _within(part: str, whole: str) -> bool:
    return f" {part} " in f" {whole} "


def repeats(answer: str, counter_example: str) -> bool:
    """Whether the answer says nothing the counter-example does not: it is the
    counter-example, or a part of it of at least `_COPY_MIN_WORDS` words.

    Case, spacing and punctuation aside, so a curly apostrophe or a dash for a
    comma is still the same answer. Words shared in another order are not: "I
    have not refunded your gift code" shares nearly every word of "Sure, I have
    refunded your gift code" and says the opposite.
    """
    said, bad = _sequence(answer), _sequence(counter_example)
    if not said or not bad:
        return False
    return said == bad or (len(said.split()) >= _COPY_MIN_WORDS and _within(said, bad))


def copies(answer: str, counter_example: str) -> bool:
    """Whether the answer repeats the counter-example word for word, or is a part of it.

    As `repeats`, and also an answer that holds the whole counter-example with
    more around it - which may be the fix as much as the mistake, so it takes a
    quote to tell which.
    """
    said, bad = _sequence(answer), _sequence(counter_example)
    return repeats(answer, counter_example) or bool(said and bad and _within(bad, said))


def _counter_unsupported(quotes: Sequence[str], answer: str, counter_example: str) -> bool:
    """Whether a pass on not repeating the counter-example has nothing to stand on.

    A quote of the answer the counter-example does not also say backs it, so
    an answer that keeps the counter-example and adds what it lacked passes on
    the addition. Quoting only what the two share points at the mistake rather
    than away from it. With nothing quoted, a copy of the counter-example
    cannot pass on being unlike it. Quotes compare by whole words, as `copies`
    does, so a quote cut mid-word sets nothing apart.
    """
    said, bad = _sequence(answer), _sequence(counter_example)
    held = [words for words in map(_sequence, quotes) if words and _within(words, said)]
    if any(not _within(words, bad) for words in held):
        return False
    return bool(held) or copies(answer, counter_example)


def graded(
    criteria: Sequence[JudgeCriterion],
    verdict: JudgeVerdict,
    *,
    answer: str,
    scale_max: int,
    pass_at: int,
    run_id: UUID,
    counter_example: str | None = None,
) -> list[ScorerResult]:
    """The judge's grades as results; a criterion it skipped, misgraded or graded
    more than once is an error.

    A quote is checked against the part of `answer` the judge was shown; one it
    does not hold is kept beside the grade rather than in its reason. A grade
    whose reason is mostly the criterion's own words, with no quote the answer
    holds, is an error: nothing shows the judge read the answer; its words are
    kept as `judge_said`. A grade at the top of the scale with no such quote
    stands, marked `unverified`. An answer that `repeats` the counter-example
    fails on it whatever the judge said. A pass on not repeating
    `counter_example` with nothing quoted is unverified at any grade, and an
    error when the answer still copies the counter-example; so is one whose
    every quote is a passage the two share - that is the mistake, not evidence
    against it.
    """
    grades = {grade.id: grade for grade in verdict.grades}
    graded_twice = {
        id_ for id_, times in Counter(g.id for g in verdict.grades).items() if times > 1
    }
    shown = answer[:MAX_MATCH_TEXT]
    looked_in = evened(shown)
    results = []
    for criterion in criteria:
        if criterion.id == COUNTER_ID and repeats(shown, counter_example or ""):
            results.append(
                ScorerResult(
                    scorer=criterion.scorer,
                    name=criterion.name,
                    required=criterion.required,
                    status="fail",
                    score=1 / scale_max,
                    reason="The answer repeats the counter-example",
                    judge_run_id=run_id,
                )
            )
            continue
        if criterion.id in graded_twice:
            results.append(
                ScorerResult(
                    scorer=criterion.scorer,
                    name=criterion.name,
                    required=criterion.required,
                    status="error",
                    reason="The judge graded this criterion more than once",
                    reason_code="judge_graded_twice",
                    judge_run_id=run_id,
                )
            )
            continue
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
        quoted = any(holds(looked_in, quote) for quote in grade.quotes)
        if not quoted and restates(grade.reason, criterion.description):
            results.append(
                ScorerResult(
                    scorer=criterion.scorer,
                    name=criterion.name,
                    required=criterion.required,
                    status="error",
                    reason="The judge restated the criterion instead of pointing at what in the "
                    "answer meets it",
                    reason_code="judge_reason_echo",
                    judge_said=grade.reason[:MAX_REASON],
                    judge_run_id=run_id,
                )
            )
            continue
        countered = criterion.id == COUNTER_ID and grade.score >= pass_at
        if countered and _counter_unsupported(grade.quotes, shown, counter_example or ""):
            results.append(
                ScorerResult(
                    scorer=criterion.scorer,
                    name=criterion.name,
                    required=criterion.required,
                    status="error",
                    reason="The judge passed the answer as unlike the counter-example, though "
                    "the answer repeats it or the judge quoted only what the two share",
                    reason_code="judge_counter_unsupported",
                    judge_said=grade.reason[:MAX_REASON],
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
                reason=f"{grade.score}/{scale_max}: {grade.reason}"[:MAX_REASON],
                rule=grade.rule.strip() or None,
                unverified=(grade.score == scale_max or countered) and not quoted,
                unverified_quotes=_unverified(grade.quotes, looked_in),
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
    said: str | None = None,
) -> list[ScorerResult]:
    """Every criterion the judge could not grade, with why, and what it said if it answered."""
    return [
        ScorerResult(
            scorer=criterion.scorer,
            name=criterion.name,
            required=criterion.required,
            status="skipped" if skipped else "error",
            reason=reason,
            reason_code=code,
            judge_said=said,
            judge_run_id=run_id,
        )
        for criterion in criteria
    ]
