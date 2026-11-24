"""Browser teaching request and response bodies. Responses hold sanitized metadata only."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.browser_teaching import (
    MAX_EVENTS,
    MAX_ORIGINS,
    MAX_PARAMETERS,
    CapturedStep,
    ReviewedStep,
    TeachingReason,
    TeachingState,
    teaching_origin,
)
from app.schemas.skill import skill_name_refusal


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class TeachingStart(_Request):
    """Start recording in a browser view the caller holds right now.

    Organization and person come from the authenticated context, never from here.
    """

    run_id: UUID
    call_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=160)
    allowed_origins: tuple[str, ...] = Field(min_length=1, max_length=MAX_ORIGINS)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Use a short plain title")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        origins = tuple(teaching_origin(value) for value in values)
        if len(set(origins)) != len(origins):
            raise ValueError("List each origin once")
        return origins


class TeachingChange(_Request):
    """Pause or resume capture. The current revision is sent in `If-Match`."""

    action: Literal["pause", "resume"]


class TeachingReview(_Request):
    """Replace the reviewed labels and parameter names. The current revision is sent in `If-Match`.

    Each step is named by its sequence. A step with neither a label nor a
    parameter is simply not reviewed yet. Sending exactly the stored review again
    changes nothing, whatever the revision.
    """

    action: Literal["review"]
    steps: tuple[ReviewedStep, ...] = Field(max_length=MAX_EVENTS)

    @field_validator("steps")
    @classmethod
    def _steps(cls, steps: tuple[ReviewedStep, ...]) -> tuple[ReviewedStep, ...]:
        sequences = [step.sequence for step in steps]
        if len(set(sequences)) != len(sequences):
            raise ValueError("Review each step once")
        if len({step.parameter for step in steps if step.parameter}) > MAX_PARAMETERS:
            raise ValueError(f"Use at most {MAX_PARAMETERS} parameters")
        return tuple(sorted(steps, key=lambda step: step.sequence))


TeachingEdit = Annotated[TeachingChange | TeachingReview, Field(discriminator="action")]


class TeachingPropose(_Request):
    """Ask for one skill proposal from the reviewed steps. The current revision is sent in `If-Match`."""

    name: str = Field(
        min_length=1, max_length=64, description="The new skill's name, such as `download-invoice`"
    )

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        refusal = skill_name_refusal(value)
        if refusal is not None:
            raise ValueError(refusal)
        return value


class TeachingRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    agent_id: UUID
    run_id: UUID
    call_id: str
    tab_id: str
    title: str
    allowed_origins: tuple[str, ...]
    status: TeachingState
    revision: int
    reason_code: TeachingReason | None
    events: tuple[CapturedStep, ...]
    review: tuple[ReviewedStep, ...]
    parameters: tuple[str, ...]
    proposal_name: str | None
    proposal_id: UUID | None
    created_at: datetime
    capture_ends_at: datetime
    expires_at: datetime
