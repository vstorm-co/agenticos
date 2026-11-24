"""Eval-driven tool tuning (#11): score a tool against eval cases, draft tuning proposals.

The tuning layer on top of the failure-learning loop (#32). A tuning run
takes one tool and a set of eval cases - the cases #32's `agent_eval_cases`
holds, each with an `EvalExpectation` - and scores how the tool behaved on
them: per case, did it pass, and when it did not, why. The failures sort
into seven classes, and actionable classes draft tuning proposals -
prompt wording, tool parameters, or which tool is picked.

What this module does NOT do, deliberately:

- It never judges an answer. The per-case verdict - passed or not, and what
  the answer said - arrives already judged, as #32's `judge()` judged it
  (`app.services.eval_judging.judge`, shared with workflow evals). Scoring
  consumes `(passed, shown)` pairs; it does not re-implement matching.
- It never applies a proposal. A proposal is a draft with its evidence, for
  a human to approve. Applying an instruction change goes through #32's
  proposal apply (eval-gated, audited); a skill change through the learned-
  skill path (#9). There is no apply function here to call by mistake.
- It stores nothing. The record a run keeps is a plain dict built by
  `tuning_run_record`, written onto the run manifest by the capability
  (`RunRecorder.eval_tool_tuning_runs`, capped, no migration).

Seam with #32, which has not merged yet: #32's try runner produces the
judged per-case results (`EvalTryCaseRead` - old/new pass, judge's shown
text, and the tool calls from the test runs' manifests). Until it lands,
the capability's tool takes those results as its input - a caller hands
this module judged cases, it never runs an eval itself.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

#: The expectation kinds #32's `EvalExpectation` allows. A judged case names
#: one of these; anything else is a caller error, not a new kind.
EXPECTATION_KINDS = ("contains", "not_contains", "equals")

#: How much of the judge's shown answer a per-case record keeps.
_SHOWN_ANSWER = 500

FailureClass = Literal[
    "passed",
    "not_called",
    "wrong_tool",
    "transient",
    "authorization",
    "bad_arguments",
    "unknown",
    "wrong_answer",
]

#: The order failure classes are reported in when counts tie: the class
#: closest to the tool itself - it was never called - first.
_FAILURE_ORDER = (
    "not_called",
    "wrong_tool",
    "transient",
    "authorization",
    "bad_arguments",
    "unknown",
    "wrong_answer",
)

TuningKind = Literal["prompt_wording", "tool_parameters", "tool_choice"]


@dataclass(frozen=True)
class ToolCallObservation:
    """One tool call a judged case's run made, as the manifest recorded it.

    Attributes:
        tool: The tool that was called, by name.
        arguments: The arguments it was called with, summarised - keys and
            short values, never a whole payload.
        error: What the call failed with, or `None` when it returned cleanly.
        error_type: The exception class, when the caller recorded one.
    """

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None

    def __post_init__(self) -> None:
        if not self.tool.strip():
            raise ValueError("A tool call observation names no tool")


@dataclass(frozen=True)
class JudgedCase:
    """One eval case, already judged - the input a tuning run scores.

    This is #32's `judge()` output, not a second judge: `passed` and `shown`
    are what the judge said about the case's answer against its expectation,
    and `tool_calls` are what the case's test run called. The expectation's
    kind and value ride along so a proposal can quote what the answer was
    supposed to say.

    Attributes:
        name: The case, as its author named it.
        expectation_kind: `contains`, `not_contains`, or `equals`.
        expectation_value: What the answer was supposed to say (or not say).
        passed: Whether the judge said the answer met the expectation.
        shown: What the answer said at the expectation's field, clipped.
        tool_calls: Every tool call the case's run made, in order.
    """

    name: str
    expectation_kind: str
    expectation_value: str
    passed: bool
    shown: str = ""
    tool_calls: tuple[ToolCallObservation, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("A judged case names no case")
        if self.expectation_kind not in EXPECTATION_KINDS:
            raise ValueError(f"Unknown expectation kind: {self.expectation_kind!r}")
        if not isinstance(self.passed, bool):
            raise TypeError("A judged case's verdict is a bool, not a guess")


@dataclass(frozen=True)
class CaseScore:
    """One case scored for one tool: its verdict, and why it failed."""

    name: str
    classification: FailureClass
    passed: bool
    shown: str
    detail: str
    #: The other tools the run picked instead, when the class is `wrong_tool`.
    other_tools: tuple[str, ...] = ()
    #: What the expectation asked the answer to say, when the class is
    #: `wrong_answer` - so a proposal can quote it without re-reading the case.
    expectation_value: str = ""


@dataclass(frozen=True)
class ToolTuningScore:
    """A tool scored across a set of eval cases.

    Attributes:
        tool: The tool that was scored.
        total: Cases scored. `passed` of them passed.
        passed: Cases the tool passed.
        pass_rate: `passed / total`, or 0.0 when no cases were scored.
        cases: Every case, in the order it was scored.
        dominant_failure: The most common failure class, or `None` when
            nothing failed. Ties break towards the class closest to the
            tool itself (`not_called` before `wrong_tool`, and so on).
    """

    tool: str
    total: int
    passed: int
    pass_rate: float
    cases: tuple[CaseScore, ...]
    dominant_failure: FailureClass | None


@dataclass(frozen=True)
class TuningProposal:
    """One tuning change, drafted - never applied - with its evidence.

    Attributes:
        kind: What sort of change this is - prompt wording, tool parameters,
            or which tool is picked.
        tool: The tool the change tunes.
        title: The change in one line.
        current: What is true now, as observed.
        proposed: The change, as a concrete instruction or constraint.
        rationale: Why, citing the score.
        evidence: The failing cases this rests on, by name.
        status: Always `draft`. A proposal becomes real only when a human
            applies it through #32 (instructions) or #9 (skills).
    """

    kind: TuningKind
    tool: str
    title: str
    current: str
    proposed: str
    rationale: str
    evidence: tuple[str, ...]
    status: Literal["draft"] = "draft"


def classify(tool: str, case: JudgedCase) -> CaseScore:
    """Score one case for one tool: its verdict, and which failure it is.

    A case that passed is `passed`, whatever the tool did. A failing case
    sorts by what the run shows: the tool never called, another tool picked,
    a transient or authorization error, invalid arguments, an unknown error,
    or a clean call whose answer still missed the expectation.
    """
    if case.passed:
        return CaseScore(
            name=case.name,
            classification="passed",
            passed=True,
            shown=case.shown[:_SHOWN_ANSWER],
            detail="The answer met the expectation.",
        )
    calls = [call for call in case.tool_calls if call.tool == tool]
    if not case.tool_calls:
        return CaseScore(
            name=case.name,
            classification="not_called",
            passed=False,
            shown=case.shown[:_SHOWN_ANSWER],
            detail=f"No tool was called, so {tool} never ran.",
        )
    if not calls:
        others = sorted({call.tool for call in case.tool_calls})
        return CaseScore(
            name=case.name,
            classification="wrong_tool",
            passed=False,
            shown=case.shown[:_SHOWN_ANSWER],
            detail=f"{tool} was not picked; the run called {', '.join(others)} instead.",
            other_tools=tuple(others),
        )
    errored = [call for call in calls if call.error]
    if errored:
        classification = _classify_tool_error(errored[0].error, errored[0].error_type)
        return CaseScore(
            name=case.name,
            classification=classification,
            passed=False,
            shown=case.shown[:_SHOWN_ANSWER],
            detail=(
                f"{tool} failed because of invalid arguments: {errored[0].error}"
                if classification == "bad_arguments"
                else f"{tool} failed with {errored[0].error_type or 'an unclassified error'}: "
                f"{errored[0].error}"
            ),
        )
    return CaseScore(
        name=case.name,
        classification="wrong_answer",
        passed=False,
        shown=case.shown[:_SHOWN_ANSWER],
        detail=(
            f"{tool} ran cleanly, but the answer still missed the expectation "
            f"({case.expectation_kind} {case.expectation_value!r})."
        ),
        expectation_value=case.expectation_value,
    )


def _classify_tool_error(error: str | None, error_type: str | None) -> FailureClass:
    normalized = f"{error_type or ''} {error or ''}".casefold()
    if re.search(r"\b(?:401|403)\b|unauthori[sz]ed|forbidden", normalized):
        return "authorization"
    if re.search(
        r"\b(?:timeout|timed out|connection(?:error| refused| reset| aborted| failed)?|"
        r"connectiontimeout|ratelimit|rate.?limit|429|too many requests)\b",
        normalized,
    ):
        return "transient"
    if re.search(
        r"\b(?:argument(?:s)?[_ ]?error|bad[_ ]?arguments?|bad query|"
        r"invalid[_ ]?arguments?|invalid[_ ]?parameters?|"
        r"validation(?:error|[_ ]?error| failed)?)\b",
        normalized,
    ):
        return "bad_arguments"
    return "unknown"


def score_tool(tool: str, cases: list[JudgedCase]) -> ToolTuningScore:
    """Score a tool across a set of judged eval cases."""
    if not tool.strip():
        raise ValueError("A tuning run scores a named tool")
    scored = tuple(classify(tool, case) for case in cases)
    passed = sum(1 for case in scored if case.passed)
    total = len(scored)
    failures: dict[str, int] = {}
    for case in scored:
        if case.classification != "passed":
            failures[case.classification] = failures.get(case.classification, 0) + 1
    dominant: FailureClass | None = None
    if failures:
        most = max(failures.values())
        dominant = next(
            cls  # type: ignore[assignment]
            for cls in _FAILURE_ORDER
            if failures.get(cls) == most
        )
    return ToolTuningScore(
        tool=tool,
        total=total,
        passed=passed,
        pass_rate=(passed / total) if total else 0.0,
        cases=scored,
        dominant_failure=dominant,
    )


def propose_tuning(score: ToolTuningScore) -> tuple[TuningProposal, ...]:
    """Draft one tuning proposal per failure class in a score.

    One proposal per class, not per case: five cases failing the same way
    are one tuning problem, not five. A score with no failures drafts
    nothing - there is nothing to tune. Every proposal is a draft; nothing
    here applies, and nothing here claims the draft will fix the cases -
    that is what #32's eval gate is for, once the proposal is applied by
    a human and tried again.
    """
    failed = [case for case in score.cases if not case.passed]
    if not failed:
        return ()
    by_class: dict[str, list[CaseScore]] = {}
    for case in failed:
        by_class.setdefault(case.classification, []).append(case)
    proposals: list[TuningProposal] = []
    rate = f"{score.passed}/{score.total} cases passed"
    if "not_called" in by_class:
        names = [case.name for case in by_class["not_called"]]
        proposals.append(
            TuningProposal(
                kind="tool_choice",
                tool=score.tool,
                title=f"Route these requests to {score.tool}",
                current=(
                    f"No routing rule names {score.tool} for these requests, "
                    f"so no tool ran on {len(names)} case(s)."
                ),
                proposed=(
                    f"Name {score.tool} in the agent's instructions as the tool "
                    f"for requests like {', '.join(names)}: call it before "
                    f"answering, and do not answer from memory instead."
                ),
                rationale=f"The tool was never called on these cases ({rate}).",
                evidence=tuple(names),
            )
        )
    if "wrong_tool" in by_class:
        names = [case.name for case in by_class["wrong_tool"]]
        others = sorted({tool for case in by_class["wrong_tool"] for tool in case.other_tools})
        proposals.append(
            TuningProposal(
                kind="tool_choice",
                tool=score.tool,
                title=f"Prefer {score.tool} over {', '.join(others) or 'other tools'}",
                current=(
                    f"The run picked {', '.join(others) or 'another tool'} "
                    f"instead of {score.tool} on {len(names)} case(s)."
                ),
                proposed=(
                    f"Say in the agent's instructions when {score.tool} is the "
                    f"right tool and when {', '.join(others) or 'the other tools'} "
                    f"are not, so the model stops picking the wrong one for "
                    f"requests like {', '.join(names)}."
                ),
                rationale=f"The wrong tool was picked on these cases ({rate}).",
                evidence=tuple(names),
            )
        )
    if "bad_arguments" in by_class:
        names = [case.name for case in by_class["bad_arguments"]]
        proposals.append(
            TuningProposal(
                kind="tool_parameters",
                tool=score.tool,
                title=f"Constrain {score.tool}'s arguments",
                current=(
                    f"{score.tool} was called and failed on {len(names)} case(s): "
                    + "; ".join(case.detail for case in by_class["bad_arguments"])
                ),
                proposed=(
                    f"Constrain {score.tool}'s arguments in the tool's "
                    f"description - the required fields, their ranges, and "
                    f"what counts as a valid value - so the model stops "
                    f"calling it with arguments that fail."
                ),
                rationale=f"The tool errored on these cases ({rate}).",
                evidence=tuple(names),
            )
        )
    if "wrong_answer" in by_class:
        names = [case.name for case in by_class["wrong_answer"]]
        wanted = sorted(
            {case.expectation_value for case in by_class["wrong_answer"] if case.expectation_value}
        )
        proposals.append(
            TuningProposal(
                kind="prompt_wording",
                tool=score.tool,
                title=f"Tell {score.tool}'s caller what the answer must say",
                current=(
                    f"{score.tool} ran cleanly, but the answer still missed "
                    f"what was expected on {len(names)} case(s)."
                ),
                proposed=(
                    f"Add to the agent's instructions that an answer using "
                    f"{score.tool} must say {', '.join(wanted) or 'what the task asks for'} "
                    f"- and must not answer without the tool's result - "
                    f"for requests like {', '.join(names)}."
                ),
                rationale=f"The tool ran, but the answer missed the mark ({rate}).",
                evidence=tuple(names),
            )
        )
    return tuple(proposals)


def tuning_run_record(
    score: ToolTuningScore, proposals: tuple[TuningProposal, ...]
) -> dict[str, Any]:
    """The tuning run as a plain dict, ready for the run manifest.

    One entry per tuning run: the tool, the score, every case with its
    classification, and the draft proposals with their evidence. A record
    is a snapshot of what was scored - editing a proposal later does not
    rewrite what an earlier run found.
    """
    return {
        "tool": score.tool,
        "total": score.total,
        "passed": score.passed,
        "pass_rate": score.pass_rate,
        "dominant_failure": score.dominant_failure,
        "cases": [
            {
                "name": case.name,
                "classification": case.classification,
                "passed": case.passed,
                "shown": case.shown,
                "detail": case.detail,
            }
            for case in score.cases
        ],
        "proposals": [
            {
                "kind": proposal.kind,
                "tool": proposal.tool,
                "title": proposal.title,
                "current": proposal.current,
                "proposed": proposal.proposed,
                "rationale": proposal.rationale,
                "evidence": list(proposal.evidence),
                "status": proposal.status,
            }
            for proposal in proposals
        ],
    }
