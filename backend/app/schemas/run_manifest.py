"""What a run handed its model, on the way out.

Every field defaults to its empty answer, and that is deliberate rather than
lax. The payload is stored as it was recorded, so a row written by an older
build carries whatever that build knew how to record - and a schema that
*required* a field added later would refuse to validate exactly the old runs
somebody is looking back at, which in FastAPI is a 500 on the whole response
rather than a gap in one panel.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, JsonValue

from app.schemas.base import BaseSchema


class ManifestTool(BaseSchema):
    """One tool as the provider was told about it.

    Attributes:
        name: What the model calls it, after any per-agent renaming.
        description: The sentence the model decides on. Nowhere else readable,
            and the usual explanation for a tool an agent never calls.
        parameters_json_schema: The argument schema, verbatim.
        kind: `function`, or `output` for the tool carrying a structured answer.
    """

    name: str
    description: str | None = None
    parameters_json_schema: dict[str, Any] = Field(default_factory=dict)
    kind: str = "function"


class ManifestRequest(BaseSchema):
    """One model request the run made, and what it cost in time.

    A run is one row with one duration, and forty seconds is either one slow
    request or nine quick ones with eight tool calls between them - opposite
    problems the run row cannot tell apart.

    Attributes:
        failed: The exception class, where the request raised. Never its message:
            a provider SDK puts the failing URL, and therefore a key, in that
            string.
    """

    index: int
    started_at: datetime | None = None
    duration_ms: int = 0
    model: str | None = None
    message_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tool_calls: list[str] = Field(default_factory=list)
    finish_reason: str | None = None
    failed: str | None = None
    cache: Literal["bust", "expired"] | None = Field(
        default=None,
        description=(
            "`bust` when this request's cached prompt prefix collapsed while the provider "
            "should still have held it - the prefix moved; `expired` when its retention "
            "window had passed. Null when the cache held, or was not in play"
        ),
    )
    cache_missed_tokens: int = Field(
        default=0,
        description=(
            "Of the prefix earlier requests cached, how many tokens this request did not "
            "read back. A miss, not a bill: a compaction that shrank the request misses "
            "tokens it never sent again"
        ),
    )


class ManifestReview(BaseSchema):
    """One correction a run reviewer sent while the run went (#2106).

    Attributes:
        reviewer: The reviewer's name, as the spec gives it - what the run's model
            was told the correction came from.
        after_request: The model request the review read up to.
        steer: The correction, as the run's model received it.
    """

    reviewer: str
    after_request: int
    steer: str


class ManifestCodeCall(BaseSchema):
    """One tool call a `run_code` script made.

    Attributes:
        tool: The tool it called.
        args: Its arguments, as JSON, cut to a preview.
        status: Whether the call returned, failed or is waiting for approval.
        tool_call_id: Stable nested-call identity, absent in older manifests.
    """

    tool: str
    args: str
    status: Literal["returned", "failed", "awaiting_approval"]
    tool_call_id: str | None = Field(default=None, exclude_if=lambda value: value is None)


class ManifestCodeRun(BaseSchema):
    """One script code mode ran, and the calls it made (#2107).

    Attributes:
        tool_call_id: The `run_code` call it was, in the transcript.
        code: The script, as the model wrote it.
        calls: The tool calls the script made, in the order they started - the
            first hundred.
        omitted_calls: How many more it made beyond those listed.
    """

    tool_call_id: str
    code: str
    calls: list[ManifestCodeCall] = Field(default_factory=list)
    omitted_calls: int = 0


class ManifestSolLoopFinding(BaseSchema):
    """One finding in a sol-loop review round (#6).

    Attributes:
        id: The finding's stable id across rounds, e.g. `S1`.
        severity: `blocker`, `should`, or `nit`.
        file: The file the finding is about, empty when it names none.
        line: The line in that file, or `None` when it names none.
        claim: What is wrong, in the reviewer's words.
        fix: The reviewer's suggested fix, empty when it gave none.
        outcome: What the agent did with it - `agree-fixed`,
            `disagree-with-evidence`, or `decline-nit` - or `None` while open.
    """

    id: str
    severity: Literal["blocker", "should", "nit"]
    claim: str
    file: str = ""
    line: int | None = None
    fix: str = ""
    outcome: str | None = None


class ManifestSolLoopRound(BaseSchema):
    """One sol-loop review round (#6).

    Attributes:
        round: Which round this was, from 1.
        scope: `full` for round 1, `changed-only` after.
        verdict: `APPROVE`, `CHANGES`, `no_verdict`, or `unavailable`.
        model: The reviewer's model label.
        findings: The findings the reviewer gave this round.
        dispositions: What the agent did with the last round's findings, by id.
        stop_reason: Why the loop stopped after this round, or `None` while it
            runs on - `approved`, `nits_only`, `budget_exhausted`, `stuck`, or
            `reviewer_unavailable`.
        reason: Why the reviewer was unavailable, when that is the verdict.
        satisfied: Whether this round closes the loop.
    """

    round: int
    scope: str = "full"
    verdict: str = "no_verdict"
    model: str = ""
    findings: list[ManifestSolLoopFinding] = Field(default_factory=list)
    dispositions: dict[str, str] = Field(default_factory=dict)
    stop_reason: str | None = None
    reason: str | None = None
    satisfied: bool = False


class ManifestEvalToolTuningCase(BaseSchema):
    """One eval case scored for one tool in a tuning run (#11).

    Attributes:
        name: The case, as its author named it.
        classification: The observed result class, including transient,
            authorization, and unknown tool errors.
        passed: Whether the judge said the answer met the expectation.
        shown: What the answer said at the expectation's field, clipped.
        detail: Why the case scored as it did, in one sentence.
    """

    name: str
    classification: Literal[
        "passed",
        "not_called",
        "wrong_tool",
        "transient",
        "authorization",
        "bad_arguments",
        "unknown",
        "wrong_answer",
    ]
    passed: bool = False
    shown: str = ""
    detail: str = ""


class ManifestEvalToolTuningProposal(BaseSchema):
    """One tuning proposal a tuning run drafted (#11) - a draft, never applied.

    Attributes:
        kind: `prompt_wording`, `tool_parameters`, or `tool_choice`.
        tool: The tool the change tunes.
        title: The change in one line.
        current: What is true now, as observed.
        proposed: The change, as a concrete instruction or constraint.
        rationale: Why, citing the score.
        evidence: The failing cases this rests on, by name.
        status: Always `draft`.
    """

    kind: Literal["prompt_wording", "tool_parameters", "tool_choice"]
    tool: str
    title: str
    current: str = ""
    proposed: str = ""
    rationale: str = ""
    evidence: list[str] = Field(default_factory=list)
    status: Literal["draft"] = "draft"


class ManifestEvalToolTuningRun(BaseSchema):
    """One eval-driven tool-tuning run (#11).

    Attributes:
        tool: The tool that was scored.
        total: Cases scored. `passed` of them passed.
        passed: Cases the tool passed.
        pass_rate: `passed / total`, or 0.0 when no cases were scored.
        dominant_failure: The most common failure class, or `None` when
            nothing failed.
        cases: Every case, in the order it was scored.
        proposals: The draft proposals, one per failure class.
    """

    tool: str
    total: int = 0
    passed: int = 0
    pass_rate: float = 0.0
    dominant_failure: str | None = None
    cases: list[ManifestEvalToolTuningCase] = Field(default_factory=list)
    proposals: list[ManifestEvalToolTuningProposal] = Field(default_factory=list)


class ManifestBurstSubtask(BaseSchema):
    """One subtask's outcome in a burst (#10).

    Attributes:
        id: The subtask's stable id in the burst, e.g. `B1`.
        title: The part's title, e.g. `Part 1`.
        status: `completed`, or `failed` when the worker raised or returned
            nothing usable.
        result: The part's result, empty when it failed.
        reason: Why the part failed, or `None` when it completed.
    """

    id: str
    title: str
    status: Literal["completed", "failed"]
    result: str = ""
    reason: str | None = None


class ManifestBurstRun(BaseSchema):
    """One burst (#10).

    Attributes:
        burst: Which burst this was, from 1.
        task: The whole task the burst split.
        merged: The parts' results merged into one outcome, with failed parts
            named under a `FAILED` heading.
        results: Every part's outcome, in subtask order.
    """

    burst: int
    task: str = ""
    merged: str = ""
    results: list[ManifestBurstSubtask] = Field(default_factory=list)


class ManifestProofAttempt(BaseSchema):
    """One observed run of a proof scenario (#8).

    Attributes:
        scenario_id: The scenario this attempt ran.
        phase: `before_fix` or `after_fix`.
        status: What was observed - `passed`, `failed`, or `inconclusive`.
        evidence_kind: What kind of evidence this is - `command_output`,
            `reproduction`, `screenshot`, `ui_observation`, or `unit_test`.
            A unit-test run never counts as proof.
        command: What was run or watched.
        observed: What was actually seen, clipped before it was kept.
        duration_ms: How long the attempt took, or 0 when not measured.
        observed_at: When it ran, or `None` when not stamped.
    """

    scenario_id: str
    phase: Literal["before_fix", "after_fix"]
    status: Literal["passed", "failed", "inconclusive"]
    evidence_kind: str
    command: str = ""
    observed: str = ""
    duration_ms: int = 0
    observed_at: datetime | None = None


class ManifestProofScenario(BaseSchema):
    """One reproduction for a change, and every attempt made at it (#8).

    Attributes:
        id: The scenario's stable id, e.g. `P1`.
        name: What it reproduces, in one line.
        kind: How it runs - `command`, `reproduction`, or `ui`.
        command: What to run or watch, so the reproduction can be repeated.
        covers: The diff files this scenario exercises.
        attempts: Every attempt made at this scenario, oldest first.
    """

    id: str
    name: str
    kind: Literal["command", "reproduction", "ui"]
    command: str = ""
    covers: list[str] = Field(default_factory=list)
    attempts: list[ManifestProofAttempt] = Field(default_factory=list)


class RunManifestRead(BaseSchema):
    """The whole record, as `GET /runs/{run_id}/manifest` answers it.

    Attributes:
        instructions: The system prompt as composed and sent - the spec's text
            plus the platform's, a channel binding's, the bound skills' and
            whatever else the builder added. What the model was told, rather than
            what the spec says.
        system_prompts: Anything sent as a system part, which is separate from
            the instructions on the wire.
        tools: Every tool the provider was told about, in the order it was told.
        settings: Temperature and its neighbours, as sent. Provider passthrough -
            `extra_headers`, `extra_body` - is never recorded: it is where a
            credential rides.
        requests: One entry per model request, in order. The waterfall.
        messages: The last request's messages, dumped - the whole of what the
            model saw at the end of the run, retries and tool returns included,
            excluding request-only channel reference parts with personal
            transport metadata. Channel author references remain opaque.
        truncated: Whether the record was trimmed to fit its size ceiling. A
            reader must be able to tell a run that sent little from a record that
            was cut.
    """

    run_id: UUID
    recorded_at: datetime
    instructions: str | None = None
    system_prompts: list[str] = Field(default_factory=list)
    tools: list[ManifestTool] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    requests: list[ManifestRequest] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    transcript: list[dict[str, JsonValue]] = Field(
        default_factory=list,
        description="Standalone proactive exchanges, including the final structured response",
    )
    reviews: list[ManifestReview] = Field(default_factory=list)
    code_runs: list[ManifestCodeRun] = Field(default_factory=list)
    sol_loop_rounds: list[ManifestSolLoopRound] = Field(default_factory=list)
    eval_tool_tuning_runs: list[ManifestEvalToolTuningRun] = Field(default_factory=list)
    burst_runs: list[ManifestBurstRun] = Field(default_factory=list)
    proof_scenarios: list[ManifestProofScenario] = Field(default_factory=list)
    truncated: bool = False
