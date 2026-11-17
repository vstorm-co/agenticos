"""Browser teaching request and response bodies. Responses hold sanitized metadata only."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.browser_teaching import (
    MAX_ORIGINS,
    CapturedStep,
    TeachingReason,
    TeachingState,
    teaching_origin,
)


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
    created_at: datetime
    capture_ends_at: datetime
    expires_at: datetime
