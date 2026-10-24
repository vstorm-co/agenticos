"""Schemas for eval runs: starting one, its estimate, its results and its comparison."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.db.models.eval_run import (
    ArmRole,
    ArmSource,
    CaseAttemptStatus,
    EvalRunPurpose,
    EvalRunStatus,
)
from app.db.models.eval_suite import EvalSuiteTrigger
from app.schemas.base import BaseSchema
from app.schemas.dataset import StoredCaseContent
from app.schemas.eval_threshold import EvalSuiteCheckRead
from app.schemas.scoring import CaseScoreRead, ReviewReevaluation

CallOutcomeLiteral = Literal["executed", "blocked", "replayed", "divergent"]
FlipLiteral = Literal["regression", "fixed", "unchanged", "incomplete"]
VerdictLiteral = Literal["better", "worse", "mixed", "no_difference", "invalid"]
OverallLiteral = Literal["better", "worse"]
TrendLiteral = Literal["better", "worse", "unchanged", "unknown"]
EstimateBasisLiteral = Literal["history", "fallback", "cached"]
CaseStateLiteral = Literal["passed", "failed", "incomplete", "ungraded"]

MAX_MODELS = 4
MAX_RERUNS = 5


class ImprovementMeasurement(BaseSchema):
    """Frozen questions used for learning, measurement, and excluded evidence copies."""

    train_case_ids: list[UUID]
    holdout_case_ids: list[UUID]
    excluded_case_ids: list[UUID]
    gradable_holdout: int
    minimum_holdout: int


class KnowledgeCheckRecord(BaseSchema):
    topic_id: UUID
    draft_hash: str
    mode: Literal["context", "retrieval"] = "context"
    supported: bool
    invalidated: bool = False
    collection_name: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = Field(default=None, ge=1)
    embedding_estimate_usd: Decimal = Field(default=Decimal(0), ge=0)
    embedding_rerun_ceiling_usd: Decimal = Field(default=Decimal(0), ge=0)


class ProposalCheckRecord(BaseSchema):
    """What a check of the authoring assistant's proposal measured, kept on its run.

    Attributes:
        kind: Suggestions to an agent's draft, or a proposed skill or context
            file body served in place of the stored one.
        base_version: The version the change was measured on: the latest
            published version the draft is based on for suggestions, the
            version production runs for a skill or context file. Null for an
            agent never published.
        on_draft: The suggestions were measured on the draft as it stands,
            because it differs from `base_version` - the baseline is the draft
            itself, so only the suggestions differ between the two sides.
        suggestions: How many suggestions the candidate carries.
    """

    kind: Literal["agent", "skill", "context"]
    base_version: int | None
    on_draft: bool = False
    suggestions: int = Field(ge=1)
    improvement_run_id: UUID | None = None
    evidence_run_ids: list[UUID] = Field(default_factory=list)
    measurement: ImprovementMeasurement | None = None
    knowledge: KnowledgeCheckRecord | None = None


class EvalRunRequest(BaseSchema):
    """What to run, as a person asks for it - the same body estimates and starts.

    Attributes:
        dataset_id: The dataset whose cases are answered.
        dataset_version: Which version of it; the latest when omitted.
        environment_id: The agent's environment whose test connections the
            cases run on. Only the connections and the tracing are taken from
            it - never the version it pins.
        candidate: Run a published version, or the agent's draft as it is now.
        version: The published version to run; the current one when omitted.
        model_profile_ids: Run the candidate on each of these models side by
            side. Empty runs it on the model its spec names.
        paired_baseline: Run a baseline in this same run, so both sides meet
            the same provider on the same day. A recent enough matching
            baseline is reused instead of run again.
        baseline_version: The version the candidate is measured against. The
            published version for a draft, the one before it for a version.
        baseline_run_id: An earlier run of the same agent and dataset to
            measure against instead, when no baseline runs beside the candidate:
            flipped cases are rerun against it, and the verdict is read from it.
        from_recordings: Answer tool calls from the run each case was taken
            from, where there is one, instead of calling anything.
        live_reads: With recordings, let a call the recording cannot answer
            run when the isolation allows it to read.
        reruns: How many times a flipped case is rerun to confirm the flip.
    """

    dataset_id: UUID
    dataset_version: int | None = Field(default=None, ge=1)
    environment_id: UUID | None = None
    candidate: Literal["version", "draft"] = "version"
    version: int | None = Field(default=None, ge=1)
    model_profile_ids: list[UUID] = Field(default_factory=list, max_length=MAX_MODELS)
    paired_baseline: bool = False
    baseline_version: int | None = Field(default=None, ge=1)
    baseline_run_id: UUID | None = None
    from_recordings: bool = False
    live_reads: bool = False
    reruns: int | None = Field(default=None, ge=0, le=MAX_RERUNS)
    case_ids: list[UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=1000,
        description="Only these case identities in the selected version; omitted runs every case",
    )

    @field_validator("case_ids")
    @classmethod
    def _distinct_cases(cls, value: list[UUID] | None) -> list[UUID] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("Name each case once")
        return value

    @field_validator("model_profile_ids")
    @classmethod
    def _distinct(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Name each model once")
        return value


class ArmEstimate(BaseSchema):
    """What one arm is expected to cost, and what the number rests on."""

    role: ArmRole
    source: ArmSource
    version_number: int | None
    model_profile_id: UUID | None
    model_label: str
    cost_per_case_usd: Decimal
    cost_usd: Decimal
    basis: EstimateBasisLiteral
    cached_from_run_id: UUID | None = None
    cached_at: datetime | None = None


class EvalRunEstimate(BaseSchema):
    """The spend a run asks consent for, against what is left to spend.

    `total_usd` is what the run costs if no case flips. `rerun_ceiling_usd` is
    the most the confirmation reruns can add on top, which only happens to the
    cases that flip. The `*_after_usd` fields are what the agent's and the
    organization's monthly budgets keep for live traffic once `total_usd` is
    spent; `None` where there is no cap.
    """

    cases: int
    arms: list[ArmEstimate]
    judge_usd: Decimal
    judge_model_profile_id: UUID | None = Field(
        default=None,
        description="The model the judge would grade on; null when no judge grades the run",
    )
    total_usd: Decimal
    rerun_ceiling_usd: Decimal
    agent_remaining_usd: Decimal | None
    org_remaining_usd: Decimal | None
    agent_after_usd: Decimal | None
    org_after_usd: Decimal | None
    affordable: bool
    missing_baseline_version: int | None = Field(
        default=None,
        description=(
            "The version this run would be measured against, when no earlier run of it "
            "was graded and executed the same way; the run then has no baseline unless "
            "that version runs beside it (`paired_baseline`)"
        ),
    )
    ungraded_cases: int = Field(
        default=0,
        description=(
            "How many of the cases nothing in the dataset's scoring would grade - "
            "with AI assistance off, the judge grades none. Any makes the result "
            "inconclusive"
        ),
    )
    proposal_check: ProposalCheckRecord | None = Field(
        default=None,
        description="What a check of the authoring assistant's proposal would measure; null otherwise",
    )


class ArmSummaryRead(BaseSchema):
    """Both axes for one arm: quality as each case settled, efficiency over first attempts."""

    cases: int
    passed: int
    failed: int = Field(description="Cases whose settled verdict is failed")
    incomplete: int = Field(
        description=(
            "Undecided because something failed on them - the provider, a scorer, the "
            "run itself - or their tries tied"
        )
    )
    ungraded: int = Field(description="Undecided because nothing in the scoring grades them")
    crashed: int = Field(
        default=0,
        description=(
            "First answers the agent's run failed before giving, counted independently "
            "of the settled verdict; each fails a suite even when its reruns pass"
        ),
    )
    pass_rate: float | None = Field(
        description=(
            "Passed over decided cases, each case settled by the majority of its "
            "decided attempts - its first alone when it was not rerun"
        )
    )
    first_pass_rate: float | None = Field(description="The pass rate of the first attempts alone")
    cost_usd: Decimal
    cost_per_pass_usd: Decimal | None
    avg_tokens: float | None
    p50_ms: float | None
    p95_ms: float | None


class EvalUngradedCaseRead(BaseSchema):
    """A case one side's first answer to was not graded."""

    case_id: UUID
    input: str


class EvalRunArmRead(BaseSchema):
    id: UUID
    role: ArmRole
    position: int
    source: ArmSource
    agent_version_id: UUID | None
    version_number: int | None
    model_profile_id: UUID | None
    model_label: str
    reused_from_arm_id: UUID | None
    spec_hash: str = Field(description="A fingerprint of the spec that answered")
    skill_ids: list[UUID] = Field(
        default_factory=list,
        description="The skills this side served a proposed body for instead of the stored one",
    )
    context_ids: list[UUID] = Field(
        default_factory=list,
        description="The context files this side served a proposed body for instead of the stored one",
    )
    summary: ArmSummaryRead
    by_tag: dict[str, ArmSummaryRead]
    ungraded_cases: list[EvalUngradedCaseRead] = Field(
        default_factory=list,
        description=(
            "The cases this side's first answer counts as neither passed nor failed "
            "because a scorer reached no verdict and no person decided"
        ),
    )
    unsent_failed: int = Field(
        default=0,
        description="This side's failed first answers not yet in the review queue",
    )
    failed_alike: str | None = Field(
        default=None,
        description=(
            "The error every one of this side's first answers failed with, when they all "
            "failed with the same one - a configuration to fix, not answers to read"
        ),
    )


class ComparisonSide(BaseSchema):
    """Which run and arm one side of a comparison is, labelled the way it is shown."""

    run_id: UUID
    arm_id: UUID
    role: ArmRole
    source: ArmSource
    version_number: int | None
    model_label: str
    dataset_version: int
    finished_at: datetime | None


class EvalOutcomeRead(BaseSchema):
    """How a finished run's first candidate came out against its baseline.

    `verdict` and `baseline` are null when there was nothing to compare with:
    the run is then the first result the next version is measured against. Pass
    rates are over the cases both sides answered, or over every case without a
    baseline, settled as `ArmSummaryRead.pass_rate` is, and count a person's
    decision before the scorers'.
    """

    candidate_arm_id: UUID
    candidate_crashed: int = Field(
        ge=0, description="Candidate first answers whose agent run failed, even when reruns pass"
    )
    verdict: VerdictLiteral | None
    overall: OverallLiteral | None
    baseline: ComparisonSide | None
    regressions_confirmed: int
    fixed_confirmed: int
    candidate_pass_rate: float | None
    baseline_pass_rate: float | None
    candidate_first_pass_rate: float | None
    baseline_first_pass_rate: float | None
    candidate_undecided: int = Field(
        description="The candidate's cases neither passed nor failed, whatever kept them undecided"
    )


class RoutingErrorRead(BaseSchema):
    """Why a run could not send its scores to review."""

    code: str
    message: str


class EvalRunSuiteRead(BaseSchema):
    """The eval suite that started a run, and what made it run."""

    id: UUID
    name: str
    trigger: EvalSuiteTrigger


class EvalRunRead(BaseSchema):
    """One eval run, with each arm's results so far."""

    id: UUID
    agent_id: UUID
    dataset_id: UUID
    dataset_name: str
    review: ReviewReevaluation | None = None
    dataset_version: int
    environment_id: UUID | None
    status: EvalRunStatus
    purpose: EvalRunPurpose
    paired: bool
    from_recordings: bool
    live_reads: bool
    reruns: int
    estimate_usd: Decimal
    rerun_ceiling_usd: Decimal = Field(
        description="What confirming reruns may add on top of the estimate"
    )
    cost_usd: Decimal
    cost_is_partial: bool
    attempts_done: int
    attempts_total: int
    cases: int = Field(description="The cases the run answers")
    first_done: int = Field(description="First answers finished, every arm's")
    first_total: int = Field(
        description="First answers in all; the rest of `attempts_total` are confirming reruns"
    )
    outcome: EvalOutcomeRead | None = Field(
        description="The verdict once the run has ended; null while it answers"
    )
    routed_to_review: int = Field(
        description=(
            "How many of its scores the run sent to review itself: its confirmed "
            "regressions and the answers no scorer reached a verdict on"
        )
    )
    routed_replacing: int = Field(
        description=(
            "How many older scores of the same cases, still waiting in review, the "
            "ones it sent replaced"
        )
    )
    judge_model_profile_id: UUID | None = Field(
        default=None,
        description="The model the judge graded this run's answers on; null when none did",
    )
    routing_error: RoutingErrorRead | None = Field(
        default=None,
        description=(
            "Why the run could not send its scores to review itself; null when it "
            "could. The run still completed, and its answers can be sent by hand"
        ),
    )
    ungraded_score_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "This run's scores that count as neither passed nor failed because a "
            "scorer reached no verdict - the judge errored or was skipped - and no "
            "person decided: what grading again can settle"
        ),
    )
    excluded_case_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Cases of the dataset version the run does not answer, because they were "
            "taken from the conversations a proposal it checks was derived from - a "
            "change is never measured on the data it was fitted to"
        ),
    )
    suite: EvalRunSuiteRead | None = Field(
        default=None,
        description="The eval suite that started this run; null for one started by hand",
    )
    draft_changed: bool | None = Field(
        default=None,
        description=(
            "Whether the agent's draft changed since this run tested it. Sent on the "
            "single-run read of a run of the draft; null otherwise"
        ),
    )
    proposal_check: ProposalCheckRecord | None = Field(
        default=None,
        description=(
            "What a check of the authoring assistant's proposal measured; null for any "
            "other run. Such a run sends nothing to review by itself"
        ),
    )
    suite_check: EvalSuiteCheckRead | None = Field(
        default=None,
        description=(
            "What the eval suite a check of suggestions ran on would have said of the "
            "run. Sent on the single-run read of such a check; null otherwise"
        ),
    )
    error: str | None
    created_by_user_id: UUID | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    arms: list[EvalRunArmRead]


class EvalRunList(BaseSchema):
    items: list[EvalRunRead]
    total: int


class EvalCallRead(BaseSchema):
    """One call an attempt made, and what isolation did with it."""

    tool: str
    args: dict[str, Any]
    outcome: CallOutcomeLiteral
    reason: str | None = None


class EvalAttemptRead(BaseSchema):
    id: UUID
    arm_id: UUID
    attempt: int
    status: CaseAttemptStatus
    agent_run_id: UUID | None
    answer: str | None
    calls: list[EvalCallRead]
    cost_usd: Decimal | None
    cost_is_partial: bool
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    error: str | None
    outcome: bool | None
    state: CaseStateLiteral = Field(
        description=(
            "How the attempt came out: `failed` includes a run the agent crashed; "
            "`incomplete` is one the provider or a scorer failed on, or that never ran; "
            "`ungraded` is an answer nothing grades"
        )
    )
    score: CaseScoreRead | None


class EvalCaseRead(BaseSchema):
    """One case of the run, with every attempt every arm made at it."""

    case_id: UUID
    case_revision_id: UUID
    position: int
    input: str
    tags: list[str]
    expectation: StoredCaseContent | None = Field(
        description=(
            "What the case expects, as the revision the run answered holds it - "
            "the reference, the counter-example, the calls and the checks"
        )
    )
    attempts: list[EvalAttemptRead]


class EvalCaseLinkRead(BaseSchema):
    """Which eval run and case one agent run answered or graded - where it is read."""

    eval_run_id: UUID
    agent_id: UUID
    case_id: UUID
    dataset_name: str
    case_input: str
    graded: bool = Field(
        default=False, description="The run is the judge grading the case, not the agent answering"
    )


class EvalCaseList(BaseSchema):
    items: list[EvalCaseRead]
    total: int


class CaseFlipRead(BaseSchema):
    case_id: UUID
    input: str = Field(description="The question the case asks")
    flip: FlipLiteral
    confirmed: bool
    baseline: bool | None
    candidate: bool | None
    baseline_reruns: list[bool | None]
    candidate_reruns: list[bool | None]
    tags: list[str]
    candidate_error: str | None = Field(
        default=None,
        description="Why the candidate's first answer failed, when its run crashed rather than answered",
    )


class EfficiencyRead(BaseSchema):
    cost_per_pass: TrendLiteral
    avg_tokens: TrendLiteral
    p50_ms: TrendLiteral
    p95_ms: TrendLiteral


class EvalComparisonRead(BaseSchema):
    """A candidate arm against its baseline, quality first and efficiency beside it.

    `baseline` is null when there is nothing to compare with yet - the agent's
    previous version was never run on this dataset. `verdict` rests on the
    confirmed flips: `worse` with a confirmed regression, `better` with
    confirmed fixes alone, `mixed` with both, and `invalid` when the two sides
    were scored by different scoring or a different judge. `overall` is the
    direction an exact McNemar test finds over those flips, null when they are
    too few to tell. `paired` says whether the baseline ran in the same eval run.
    """

    candidate: ComparisonSide
    baseline: ComparisonSide | None
    paired: bool
    verdict: VerdictLiteral | None
    overall: OverallLiteral | None
    p_value: float | None
    invalid_reason: str | None
    invalid_reason_code: Literal["knowledge_not_retrieved"] | None = None
    regressions_confirmed: int
    regressions_unconfirmed: int
    fixed_confirmed: int
    fixed_unconfirmed: int
    compared: int
    not_compared: int
    changed: int = Field(
        default=0,
        description=(
            "Cases both sides answered whose input or expectations changed between them; "
            "they are not compared"
        ),
    )
    baseline_rerun: bool = Field(
        default=True,
        description=(
            "Whether the baseline was asked the flipped cases again. False for a run "
            "measured against an earlier run it could not rerun - none of its flips is "
            "confirmed"
        ),
    )
    candidate_summary: ArmSummaryRead
    baseline_summary: ArmSummaryRead | None
    efficiency: EfficiencyRead | None
    cases: list[CaseFlipRead]
    flips_by_tag: dict[str, dict[FlipLiteral, int]]
