"""Starting an improvement session and reading its durable timeline."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.db.models.improvement import (
    DroppedHunk,
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)
from app.schemas.base import BaseSchema


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
    eval_usd: Decimal
    per_round_usd: Decimal
    total_usd: Decimal
    max_iterations: int
    cases: int
    evidence_runs: int
    affordable: bool
    reason: str | None = None


class ImprovementIterationRead(BaseSchema):
    id: UUID
    number: int
    authoring_request_id: UUID | None
    batch_id: UUID | None
    eval_run_ids: list[UUID]
    candidate_spec_hash: str | None
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


class ImprovementRead(BaseSchema):
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
