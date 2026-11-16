"""Authenticated teaching requests contain identities and reviewed metadata, never inputs."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.core.browser_origins import browser_origin
from app.core.browser_teaching import (
    BrowserProcedure,
    CapturedAction,
    TeachingGeneration,
    TeachingModel,
    TeachingReason,
    TeachingReview,
    TeachingState,
)


class TeachingStart(TeachingModel):
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


class TeachingChange(TeachingModel):
    action: Literal["pause", "resume", "review"]
    takeover_id: UUID | None = None
    review: TeachingReview | None = None

    @model_validator(mode="after")
    def _shape(self) -> TeachingChange:
        if (self.action == "resume") != (self.takeover_id is not None) or (
            self.action == "review"
        ) != (self.review is not None):
            raise ValueError("Supply only the data for this transition")
        return self


class TeachingPropose(TeachingModel):
    mode: Literal["reviewed", "assistant"] = "reviewed"
    max_cost_usd: Decimal | None = Field(default=None, gt=0, le=10, max_digits=12, decimal_places=6)

    @model_validator(mode="after")
    def _explicit_budget(self) -> TeachingPropose:
        if (self.mode == "assistant") != (self.max_cost_usd is not None):
            raise ValueError(
                "Assistant drafting requires an explicit budget; reviewed drafts use none"
            )
        return self


class TeachingRead(TeachingModel):
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
    status: TeachingState
    revision: int
    reason_code: TeachingReason | None
    events: tuple[CapturedAction, ...]
    review: TeachingReview | None
    procedure: BrowserProcedure | None
    generation_state: TeachingGeneration
    generation_mode: Literal["reviewed", "assistant"] | None
    max_cost_usd: Decimal | None
    proposal_id: UUID | None
    created_at: datetime
    expires_at: datetime
    capture_ends_at: datetime


class TeachingSummary(TeachingModel):
    """Owner discovery metadata; opening a capture still requires its authorized read."""

    id: UUID
    agent_id: UUID
    target_skill_id: UUID | None
    title: str = Field(max_length=160)
    allowed_origins: tuple[str, ...] = Field(max_length=10)
    source: Literal["manual", "refinement"]
    verified_success: bool
    status: TeachingState
    revision: int = Field(ge=1)
    reason_code: TeachingReason | None
    generation_state: TeachingGeneration
    proposal_id: UUID | None
    created_at: datetime
    expires_at: datetime
    capture_ends_at: datetime


class TeachingList(TeachingModel):
    """Newest-first owner page with an opaque, owner-and-organization-bound cursor."""

    items: tuple[TeachingSummary, ...] = Field(max_length=100)
    next_cursor: str | None


class TeachingPolicyWrite(TeachingModel):
    generation: UUID | None
    enabled: bool


class TeachingPolicyRead(TeachingModel):
    enabled: bool
    generation: UUID | None
    deployment_enabled: bool


class TeachingPreferenceWrite(TeachingModel):
    generation: UUID | None
    enabled: bool


class TeachingPreferenceRead(TeachingModel):
    agent_id: UUID
    enabled: bool
    generation: UUID | None
    allowed: bool


class DiscoveredProcedure(TeachingModel):
    skill_id: UUID
    skill_version_id: UUID
    skill_name: str
    procedure: BrowserProcedure
    instruction: Literal[
        "Observe the live page before every action; rematch the intended control and stop if it differs."
    ] = "Observe the live page before every action; rematch the intended control and stop if it differs."
