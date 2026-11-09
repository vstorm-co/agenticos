"""A person's resumable start in one organization, separate from tour preferences."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import BaseSchema

StartGoal = Literal["meeting", "document", "compare"]


class OnboardingUpdate(BaseSchema):
    model_config = ConfigDict(extra="forbid")
    goal: StartGoal | None = None
    dismissed: bool | None = None
    completed: Literal[True] | None = None


class OnboardingAgent(BaseSchema):
    id: UUID
    name: str


class OnboardingRead(BaseSchema):
    server_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    organization_id: UUID
    organization_name: str
    goal: StartGoal | None
    dismissed: bool = Field(
        description="The start offer is hidden by completion or a current 24-hour snooze"
    )
    completed: bool = Field(
        default=False,
        description="The guided setup was finished, independently of optional configuration or a successful run",
    )
    snoozed_until: datetime | None = Field(
        default=None, description="An unfinished start offer is hidden until this server timestamp"
    )
    can_prepare: bool
    can_configure_model: bool
    support_email: str | None
    agents: list[OnboardingAgent]
    setup_agent: OnboardingAgent | None = Field(
        default=None,
        description="An accessible shipped draft offering setup guidance only; not a runnable published agent",
    )
    latest_conversation_id: UUID | None
    latest_completed_at: datetime | None
    has_activity: bool = Field(
        default=False,
        description="Existing personal chat activity in this organization, including legacy or failed runs; not proof of success",
    )
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
