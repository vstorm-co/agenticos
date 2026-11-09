"""Explicit review and installation of a project tracker, using existing engines."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.routine_sources import Fingerprint


class ProjectTrackingReview(BaseModel):
    review_token: Fingerprint
    base_agent_id: UUID
    base_version_id: UUID
    base_agent_name: str
    resources: list[str]
    accounts: list[str]
    unavailable_sources: list[str]


class ProjectTrackingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    base_agent_id: UUID
    base_version_id: UUID
    source_review_token: Fingerprint
    publish_and_start: Literal[True]
    agent_name: str = Field(min_length=1, max_length=100)
    table_name: str = Field(min_length=1, max_length=64)
    table_visibility: Literal["private"] = "private"
    interval_seconds: int = Field(default=86_400, ge=300, le=2_678_400)


class ProjectTrackingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    agent_id: UUID
    agent_version_id: UUID
    table_id: UUID
    trigger_id: UUID
    conversation_id: UUID | None
