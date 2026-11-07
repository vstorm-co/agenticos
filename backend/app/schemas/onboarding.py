"""A person's resumable start in one organization, separate from tour preferences."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import BaseSchema

StartGoal = Literal["meeting", "document", "compare"]


class OnboardingUpdate(BaseSchema):
    model_config = ConfigDict(extra="forbid")
    goal: StartGoal | None = None
    dismissed: bool | None = None


class OnboardingAgent(BaseSchema):
    id: UUID
    name: str


class OnboardingRead(BaseSchema):
    organization_id: UUID
    organization_name: str
    goal: StartGoal | None
    dismissed: bool
    can_prepare: bool
    can_configure_model: bool
    support_email: str | None
    agents: list[OnboardingAgent]
    latest_conversation_id: UUID | None
    latest_completed_at: datetime | None
    has_result: bool = Field(
        description="A real completed chat run by this person here, never a demo or a tour dismissal"
    )


class StarterPrepare(BaseSchema):
    model_config = ConfigDict(extra="forbid")
    model_profile_id: UUID


class MemberStartRead(BaseSchema):
    has_common_agent: bool = Field(
        description="Whether both caller and member may run a published agent; no private agent names are disclosed"
    )
