"""The AI Architect as the console's widget and settings page read it (#2063)."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

AssistantStatus = Literal["ready", "needs_model", "disabled", "unavailable"]


class AssistantRead(BaseSchema):
    status: AssistantStatus = Field(
        description=(
            "`ready` to talk to; `needs_model` until the organization has a model "
            "to run it on; `disabled` when an administrator switched it off; "
            "`unavailable` when it could not be installed (the agent ceiling)"
        )
    )
    agent_id: UUID | None
    name: str
    greeting: str | None
    avatar_url: str | None = None
    avatar_color: int | None = None
    model_profile_id: UUID | None = None
    collection_ids: list[UUID] = Field(default_factory=list)
    can_use: bool = Field(
        description="Whether the caller may talk to it - `agents:run`, as for any agent"
    )
    can_configure: bool = Field(description="Whether the caller may change its settings")


class AssistantUpdate(BaseSchema):
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    greeting: str | None = Field(default=None, max_length=500)
    model_profile_id: UUID | None = None
    collection_ids: list[UUID] | None = None
