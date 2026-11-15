"""Schemas for guided team setup and resumable member onboarding."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import BaseSchema

StartGoal = Literal["meeting", "document", "compare"]


class OnboardingProfileRequest(BaseSchema):
    role: str = Field(default="general", description="User's primary role or title")
    industry: str = Field(
        default="general", description="Industry key, matching catalog or general"
    )
    team_size: str = Field(
        default="small", description="Team size description, e.g. solo, small, company"
    )
    goals: list[str] = Field(default_factory=list, description="Primary goals or pain points")
    details: str | None = Field(default=None, description="Optional extra details on workflows")
    tools: list[str] = Field(default_factory=list, description="Tools or software used")


class ProposedSpecialist(BaseSchema):
    key: str | None = Field(default=None, description="Template key if based on a catalog template")
    name: str = Field(description="Name of the specialist agent")
    role: str = Field(description="Role or specialty")
    description: str = Field(description="Description of what this agent does")
    capabilities: list[str] = Field(default_factory=list, description="Key capabilities")
    recommended: bool = Field(default=True, description="Whether selected by default")


class ProposedLead(BaseSchema):
    name: str = Field(description="Name of the lead orchestrator")
    role: str = Field(description="Lead role title")
    description: str = Field(description="Description of how the lead coordinates the team")
    starters: list[str] = Field(default_factory=list, description="Suggested starter prompts")


class OnboardingTeamProposal(BaseSchema):
    industry: str
    role: str
    rationale: str
    lead: ProposedLead
    specialists: list[ProposedSpecialist]


class CreateOnboardingTeamRequest(BaseSchema):
    lead: ProposedLead
    specialists: list[ProposedSpecialist] = Field(default_factory=list)
    project_name: str | None = None


class CreatedAgentInfo(BaseSchema):
    id: UUID
    name: str
    slug: str
    role: str
    is_lead: bool
    status: str


class OnboardingTeamResult(BaseSchema):
    lead_agent_id: UUID
    lead_agent_slug: str
    lead_conversation_id: UUID | None = None
    created_agents: list[CreatedAgentInfo] = Field(default_factory=list)
    message: str


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
