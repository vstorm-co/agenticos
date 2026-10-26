"""Starting an improvement session and reading its durable timeline."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.db.models.improvement import (
    DroppedHunk,
    EvidenceDecision,
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)
from app.schemas.base import BaseSchema
from app.schemas.knowledge_gap import CauseBranch


class ImprovementTarget(BaseSchema):
    improver_agent_id: UUID | None = None

    dataset_id: UUID | None = None
    suite_id: UUID | None = None
    window_days: int = Field(default=30, ge=1, le=90)
    max_iterations: int = Field(default=3, ge=1, le=3)

    @model_validator(mode="after")
    def _one_target(self) -> ImprovementTarget:
        if (self.dataset_id is None) == (self.suite_id is None):
            raise ValueError("Choose one dataset or one suite")
        return self


class ImprovementStart(ImprovementTarget):
    budget_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=6)


class ImprovementEstimate(BaseSchema):
    proposal_usd: Decimal
    knowledge_usd: Decimal = Decimal(0)
    eval_usd: Decimal
    per_round_usd: Decimal
    total_usd: Decimal
    max_iterations: int
    cases: int
    evidence_runs: int
    estimated_minutes: int = Field(
        description="About how long the session takes if every round runs; an estimate only"
    )
    affordable: bool
    reason: str | None = None


class ImprovementIterationRead(BaseSchema):
    id: UUID
    number: int
    authoring_request_id: UUID | None
    batch_id: UUID | None
    eval_run_ids: list[UUID]
    candidate_spec_hash: str | None
    included_hunk_ids: list[UUID] | None = None
    previous_eval_run_ids: list[UUID] = Field(default_factory=list)
    attribution_eval_run_ids: dict[UUID, UUID] = Field(default_factory=dict)
    dropped_hunk_ids: list[UUID]
    dropped: list[DroppedHunk] = Field(default_factory=list)
    verdict: ImprovementVerdict | None
    verdict_detail: dict[str, int | float | str | None] | None
    cost_usd: Decimal
    started_at: datetime
    ended_at: datetime | None


class ImprovementEvent(BaseSchema):
    action: str
    at: datetime
    stage: str | None = None
    status: str | None = None
    reason: str | None = None
    actor_user_id: UUID | None = Field(
        default=None,
        description="The person whose action this was; absent for the session's own steps",
    )
    actor_name: str | None = Field(
        default=None,
        description="That person's display name, for a reader who may see the member directory",
    )


class ImprovementRead(BaseSchema):
    published_version_id: UUID | None = None
    published_version: int | None = None
    next_version: int | None = None
    offer_automatic_check: bool = False
    can_restart: bool = False
    can_discard: bool = False
    improver_agent_id: UUID | None = None

    id: UUID
    agent_id: UUID
    created_by_user_id: UUID | None
    status: ImprovementStatus
    stage: ImprovementStage | None
    iteration: int
    max_iterations: int
    base_version_id: UUID | None
    dataset_id: UUID
    dataset_version: int
    suite_id: UUID | None
    estimate_usd: Decimal
    budget_usd: Decimal
    spent_usd: Decimal
    best_iteration_id: UUID | None
    stop_reason: StopReason | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    iterations: list[ImprovementIterationRead] = Field(default_factory=list)
    timeline: list[ImprovementEvent] = Field(default_factory=list)
    knowledge_eval_run_ids: list[UUID] = Field(default_factory=list)
    deferred_topic_ids: list[UUID] = Field(
        default_factory=list,
        description="Knowledge documents set aside with Not now in this session",
    )


class TopicDeferral(BaseSchema):
    """Set a knowledge document aside for this session, or bring it back."""

    later: bool


class ImprovementContinue(BaseSchema):
    budget_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=6)


class ContinuationEstimate(BaseSchema):
    mode: Literal["next_round", "resume", "retry"]
    number: int
    total_usd: Decimal
    budget_usd: Decimal
    affordable: bool
    candidate_hash: str


class ContinuationConsent(ImprovementContinue):
    confirmed: Literal[True]
    estimate_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=6)
    candidate_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ImprovementDiscard(BaseSchema):
    confirmed: Literal[True]


class AttributionEstimate(BaseSchema):
    changes: int
    total_usd: Decimal
    affordable: bool
    already_started: bool


class AttributionConsent(BaseSchema):
    confirmed: Literal[True]
    estimate_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=6)


class ImprovementFinish(BaseSchema):
    confirmed: Literal[True]
    publish: bool = False
    automatic_check: bool = False


class ImprovementFinished(BaseSchema):
    session: ImprovementRead
    version_id: UUID | None = None
    version: int | None = None


class KnowledgeCheckTarget(BaseSchema):
    topic_id: UUID
    mode: Literal["context", "retrieval"] = "context"
    round: int = Field(ge=1, le=3)
    case_ids: list[UUID] = Field(min_length=1, max_length=1000)


class KnowledgeCheckEstimate(BaseSchema):
    total_usd: Decimal
    affordable: bool
    can_measure: bool
    cases: int
    excluded: int
    supported: bool
    draft_hash: str
    reason: str | None = None


class KnowledgeCheckConsent(KnowledgeCheckTarget):
    confirmed: Literal[True]
    estimate_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=6)
    draft_hash: str = Field(min_length=64, max_length=64)


class ImprovementEvidenceItem(BaseSchema):
    run_id: UUID
    conversation_id: UUID | None
    kind: Literal["chat", "train_eval"]
    status: str
    rating: int
    question: str | None
    answer: str | None
    comments: list[str]
    branch: CauseBranch = Field(description="The column it shows in, a person's move included")
    reason: str | None = None
    topic_id: UUID | None = Field(
        default=None,
        description="The knowledge gap topic its miss joined, when one did; examples sharing one "
        "are one problem",
    )
    decision: EvidenceDecision | None = Field(
        default=None, description="What a person decided about it in this session; none until then"
    )


class EvidenceDecisionUpdate(BaseSchema):
    """Move one example to the other column, ignore it, or (null) take back the decision."""

    decision: EvidenceDecision | None


class ImprovementEvidence(BaseSchema):
    items: list[ImprovementEvidenceItem]
    sample_limit: int
    training_failures: int


class ImprovementSelection(BaseSchema):
    hunk_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _distinct(self) -> ImprovementSelection:
        if len(set(self.hunk_ids)) != len(self.hunk_ids):
            raise ValueError("Choose each change once")
        return self


class SelectionEstimate(BaseSchema):
    suggestions: int
    total_usd: Decimal
    affordable: bool
    candidate_hash: str


class SelectionConsent(ImprovementSelection):
    confirmed: Literal[True]
    estimate_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=6)
    candidate_hash: str = Field(min_length=64, max_length=64)
