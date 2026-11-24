"""Authenticated teaching requests contain identities and reviewed metadata, never inputs."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.core.browser_origins import browser_origin
from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingCapturedAction,
    BrowserProcedureTeachingGeneration,
    BrowserProcedureTeachingModel,
    BrowserProcedureTeachingProcedure,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingReview,
    BrowserProcedureTeachingState,
)


class BrowserProcedureTeachingStart(BrowserProcedureTeachingModel):
    request_id: UUID
    run_id: UUID
    call_id: str = Field(min_length=1, max_length=200)
    tab_id: str = Field(min_length=1, max_length=200)
    takeover_id: UUID
    title: str = Field(min_length=1, max_length=160)
    allowed_origins: tuple[str, ...] = Field(min_length=1, max_length=10)

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        canonical = tuple(browser_origin(value) for value in values)
        if len(set(canonical)) != len(canonical):
            raise ValueError("Name each exact origin once")
        return canonical


class BrowserProcedureTeachingChange(BrowserProcedureTeachingModel):
    action: Literal["pause", "resume", "review"]
    takeover_id: UUID | None = None
    review: BrowserProcedureTeachingReview | None = None

    @model_validator(mode="after")
    def _shape(self) -> BrowserProcedureTeachingChange:
        if (self.action == "resume") != (self.takeover_id is not None) or (
            self.action == "review"
        ) != (self.review is not None):
            raise ValueError("Supply only the data for this transition")
        return self


class BrowserProcedureTeachingPropose(BrowserProcedureTeachingModel):
    mode: Literal["reviewed", "assistant"] = "reviewed"
    max_cost_usd: Decimal | None = Field(default=None, gt=0, le=10, max_digits=12, decimal_places=6)

    @model_validator(mode="after")
    def _explicit_budget(self) -> BrowserProcedureTeachingPropose:
        if (self.mode == "assistant") != (self.max_cost_usd is not None):
            raise ValueError(
                "Assistant drafting requires an explicit budget; reviewed drafts use none"
            )
        return self


class BrowserProcedureTeachingRead(BrowserProcedureTeachingModel):
    id: UUID
    agent_id: UUID
    run_id: UUID
    call_id: str
    tab_id: str
    target_skill_id: UUID | None
    title: str
    allowed_origins: tuple[str, ...]
    source: Literal["manual", "refinement"]
    verified_success: bool = False
    status: BrowserProcedureTeachingState
    revision: int
    reason_code: BrowserProcedureTeachingReason | None
    events: tuple[BrowserProcedureTeachingCapturedAction, ...]
    review: BrowserProcedureTeachingReview | None
    procedure: BrowserProcedureTeachingProcedure | None
    generation_state: BrowserProcedureTeachingGeneration
    generation_mode: Literal["reviewed", "assistant"] | None
    max_cost_usd: Decimal | None
    proposal_id: UUID | None
    created_at: datetime
    expires_at: datetime
    capture_ends_at: datetime


class BrowserProcedureTeachingSummary(BrowserProcedureTeachingModel):
    """Owner discovery metadata; opening a capture still requires its authorized read."""

    id: UUID
    agent_id: UUID
    target_skill_id: UUID | None
    title: str = Field(max_length=160)
    allowed_origins: tuple[str, ...] = Field(max_length=10)
    source: Literal["manual", "refinement"]
    verified_success: bool
    status: BrowserProcedureTeachingState
    revision: int = Field(ge=1)
    reason_code: BrowserProcedureTeachingReason | None
    generation_state: BrowserProcedureTeachingGeneration
    proposal_id: UUID | None
    created_at: datetime
    expires_at: datetime
    capture_ends_at: datetime


class BrowserProcedureTeachingList(BrowserProcedureTeachingModel):
    """Newest-first owner page with an opaque, owner-and-organization-bound cursor."""

    items: tuple[BrowserProcedureTeachingSummary, ...] = Field(max_length=100)
    next_cursor: str | None


class BrowserProcedureTeachingPolicyWrite(BrowserProcedureTeachingModel):
    generation: UUID | None
    enabled: bool


class BrowserProcedureTeachingPolicyRead(BrowserProcedureTeachingModel):
    enabled: bool
    generation: UUID | None
    deployment_enabled: bool


class BrowserProcedureTeachingPreferenceWrite(BrowserProcedureTeachingModel):
    generation: UUID | None
    enabled: bool


class BrowserProcedureTeachingPreferenceRead(BrowserProcedureTeachingModel):
    agent_id: UUID
    enabled: bool
    generation: UUID | None
    allowed: bool


class BrowserProcedureTeachingDiscoveredProcedure(BrowserProcedureTeachingModel):
    skill_id: UUID
    skill_version_id: UUID
    skill_name: str
    procedure: BrowserProcedureTeachingProcedure
    instruction: Literal[
        "Observe the live page before every action; rematch the intended control and stop if it differs."
    ] = "Observe the live page before every action; rematch the intended control and stop if it differs."
