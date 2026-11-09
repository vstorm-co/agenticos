"""Durable commitments, separate from a run's internal plan checklist."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

TaskScope = Literal["private", "project", "group", "organization"]
TaskStatus = Literal["planned", "in_progress", "waiting_for_user", "blocked", "done", "cancelled"]


class BoardEnsure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: TaskScope = "private"
    scope_id: UUID | None = None


class TaskBoardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    scope_kind: TaskScope
    scope_name: str | None = None
    can_edit: bool = False
    scope_id: UUID
    table_id: UUID


class TaskFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    description: str = Field(default="", max_length=9000)
    status: TaskStatus = "planned"
    assignee_user_id: UUID | None = None
    assignee_agent_id: UUID | None = None
    start_at: AwareDatetime | None = None
    due_at: AwareDatetime | None = None
    next_actor: Literal["user", "agent"] = "user"

    @model_validator(mode="after")
    def assigned_next_actor(self) -> TaskFields:
        if self.next_actor == "agent" and self.assignee_agent_id is None:
            raise ValueError("Choose the agent responsible for the next step")
        return self


class TaskCreate(TaskFields):
    scope: TaskScope = "private"
    scope_id: UUID | None = None
    conversation_id: UUID | None = None
    external_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def default_actor(self) -> TaskCreate:
        if "next_actor" not in self.model_fields_set and self.assignee_agent_id is not None:
            self.next_actor = "agent"
        return self


class TaskUpdate(TaskFields):
    expected_revision: int = Field(ge=1)


class TaskRead(TaskFields):
    id: UUID
    table_id: UUID
    board_id: UUID
    scope: TaskScope
    scope_id: UUID
    revision: int
    conversation_id: UUID | None
    outcome_id: UUID | None
    created_at: datetime


class TaskList(BaseModel):
    items: list[TaskRead]
    has_more: bool
