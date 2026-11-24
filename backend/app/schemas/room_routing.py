"""Human-reviewed room routing; canonical task fields remain in Tasks."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.base import BaseSchema
from app.schemas.task import TaskStatus

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class RoomAgentPin(BaseSchema):
    agent_id: UUID
    version_id: UUID


class RoomAgentPinRead(RoomAgentPin):
    name: str
    current: bool


class RoomLeadPolicyWrite(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    enabled: bool
    lead_agent_id: UUID | None = None
    specialist_agent_ids: list[UUID] = Field(default_factory=list, max_length=12)
    max_items: int = Field(default=3, ge=1, le=3)

    @model_validator(mode="after")
    def valid_agents(self) -> RoomLeadPolicyWrite:
        if self.enabled and self.lead_agent_id is None:
            raise ValueError("Choose a published lead before enabling routing")
        if len(set(self.specialist_agent_ids)) != len(self.specialist_agent_ids):
            raise ValueError("Choose each specialist once")
        return self


class RoomLeadPolicyRead(BaseSchema):
    enabled: bool = False
    revision: int = 0
    lead: RoomAgentPinRead | None = None
    specialists: list[RoomAgentPinRead] = Field(default_factory=list)
    max_items: int = 3
    can_edit: bool = False
    can_ask: bool = False


class RoomTaskDescription(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    title: Title
    expected_result: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=9000)
    ]
    accountable_user_id: UUID | None = None
    due_at: AwareDatetime | None = None


class RoomProposalItem(RoomTaskDescription):
    agent_id: UUID
    agent_version_id: UUID
    existing_task_id: UUID | None = None
    expected_task_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def existing_revision(self) -> RoomProposalItem:
        if (self.existing_task_id is None) != (self.expected_task_revision is None):
            raise ValueError("An existing task needs its current revision")
        return self


class RoomProposalCreate(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    items: list[RoomProposalItem] = Field(min_length=1, max_length=3)


class RoomProposalItemRead(RoomTaskDescription):
    accountable_user_name: str | None = None
    proposal_item_id: UUID
    agent: RoomAgentPinRead | None
    existing_task_id: UUID | None = None
    expected_task_revision: int | None = None


class RoomRoutingProposalRead(BaseSchema):
    id: UUID
    conversation_id: UUID
    thread_root_message_id: UUID | None
    submission_id: UUID
    message_id: UUID
    requester_id: UUID
    lead_run_id: UUID | None
    policy_revision: int
    revision: int
    decision: Literal["pending", "accepted", "discarded"]
    items: list[RoomProposalItemRead]
    accepted_item_ids: list[UUID] = Field(default_factory=list)
    can_accept: bool
    can_discard: bool
    created_at: datetime


class RoomRoutingProposalList(BaseSchema):
    items: list[RoomRoutingProposalRead]
    has_more: bool


class RoomProposalAccept(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)
    selected_item_ids: list[UUID] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_items(self) -> RoomProposalAccept:
        if len(set(self.selected_item_ids)) != len(self.selected_item_ids):
            raise ValueError("Accept each proposed item once")
        return self


class RoomProposalDiscard(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)


class RoomTaskCard(BaseSchema):
    accountable_user_name: str | None = None
    id: UUID
    proposal_id: UUID
    proposal_item_id: UUID
    message_id: UUID
    thread_root_message_id: UUID | None
    task_id: UUID
    table_id: UUID
    accepted_revision: int
    revision: int
    title: str
    description: str
    status: TaskStatus
    next_actor: Literal["user", "agent"]
    accountable_user_id: UUID | None
    agent: RoomAgentPinRead | None
    due_at: datetime | None


class RoomTaskCardList(BaseSchema):
    items: list[RoomTaskCard]
    has_more: bool
