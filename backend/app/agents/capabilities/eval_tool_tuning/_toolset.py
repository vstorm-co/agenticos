"""The tuning run's one tool: score a tool, draft proposals, record the run."""

import json
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.eval_tool_tuning import (
    JudgedCase,
    ToolCallObservation,
    propose_tuning,
    score_tool,
    tuning_run_record,
)
from app.agents.manifest import MAX_RECORDED_EVAL_TOOL_TUNING_RUNS, RunRecorder


class _ToolCallInput(BaseModel):
    """One tool call a judged case's run made, as the manifest recorded it."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    error_type: str | None = Field(
        default=None,
        description=(
            "Exception class for the failure; timeout, connection, rate-limit, authorization, "
            "argument, and validation errors are classified by type."
        ),
    )


class _JudgedCaseInput(BaseModel):
    """One eval case, already judged - the input a tuning run scores.

    `passed` and `shown` are #32's `judge()` output for the case's answer
    against its expectation; this tool never judges an answer itself.
    """

    name: str
    expectation_kind: str
    expectation_value: str
    passed: bool
    shown: str = ""
    tool_calls: list[_ToolCallInput] = Field(default_factory=list)


def build_eval_tool_tuning_toolset(
    recorder: RunRecorder,
    max_tuning_runs: int,
) -> FunctionToolset[Any]:
    """The tuning run toolset: one tool, one tuning run per call."""
    toolset: FunctionToolset[Any] = FunctionToolset()

    @toolset.tool
    async def record_eval_tool_tuning(
        ctx: RunContext[Any],
        tool: str,
        cases: list[_JudgedCaseInput],
    ) -> str:
        """Score one tool against judged eval cases and draft tuning proposals.

        Use it after an eval try has judged a set of cases - the try #32's
        failure-learning loop runs - when the question is how one tool
        behaved on them and what should change about it. Pass the tool and
        every judged case: each case with what its answer was supposed to
        say, whether the judge said it passed, what the answer said, and
        every tool call the case's run made. For failed calls, include the
        exception class in `error_type`; timeout, connection, and rate-limit
        errors are `transient`; 401/403 errors are `authorization`;
        argument and validation errors are `bad_arguments`; other errors
        are `unknown`.
        One call is one tuning run: it
        scores the tool, classifies each failure, drafts one proposal per
        failure class, and records the run on the manifest.

        Args:
            tool: The tool to score, by name.
            cases: The judged eval cases to score it against.

        Returns:
            A JSON string with the tuning run number, the tool, how many
            cases passed, the dominant failure class, and the draft proposals
            with their kind and title. A refusal string instead when the tool
            is unnamed, a case is malformed, or no more tuning runs are
            allowed. Proposals are drafts: show them to the person and let
            them decide - never apply one, and never present a draft as a
            fix that has been made.
        """
        run_no = len(recorder.eval_tool_tuning_runs) + 1
        if run_no > max_tuning_runs:
            return (
                f"No more tuning runs: this agent allows at most "
                f"{max_tuning_runs} tuning runs and {run_no - 1} have "
                f"already run. Act on the last run's draft proposals "
                f"instead of scoring again."
            )
        if not tool.strip():
            return "Name the tool to score: a tuning run scores one tool."
        try:
            judged = [
                JudgedCase(
                    name=case.name,
                    expectation_kind=case.expectation_kind,
                    expectation_value=case.expectation_value,
                    passed=case.passed,
                    shown=case.shown,
                    tool_calls=tuple(
                        ToolCallObservation(
                            tool=call.tool,
                            arguments=call.arguments,
                            error=call.error,
                            error_type=call.error_type,
                        )
                        for call in case.tool_calls
                    ),
                )
                for case in cases
            ]
            score = score_tool(tool, judged)
        except ValueError as exc:
            return f"Cannot score these cases: {exc}"
        proposals = propose_tuning(score)
        recorder.eval_tool_tuning_runs.append(tuning_run_record(score, proposals))
        recorder.eval_tool_tuning_runs = recorder.eval_tool_tuning_runs[
            -MAX_RECORDED_EVAL_TOOL_TUNING_RUNS:
        ]
        return json.dumps(
            {
                "tuning_run": run_no,
                "tool": score.tool,
                "total": score.total,
                "passed": score.passed,
                "pass_rate": score.pass_rate,
                "dominant_failure": score.dominant_failure,
                "proposals": [
                    {
                        "kind": proposal.kind,
                        "title": proposal.title,
                        "evidence": list(proposal.evidence),
                        "status": proposal.status,
                    }
                    for proposal in proposals
                ],
                "note": ("Proposals are drafts for a human to approve; nothing was applied."),
            },
            ensure_ascii=False,
        )

    return toolset
