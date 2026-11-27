"""A chat's persistent browser or desktop, without provider handles or credentials."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.project_context import ProjectExecutionTarget

type ConversationEnvironmentKind = Literal["browser", "desktop"]
type ConversationEnvironmentState = Literal["not_started", "starting", "ready", "failed", "expired"]
type ConversationEnvironmentControl = Literal["none", "human", "agent"]
type ConversationEnvironmentRefusalCode = Literal[
    "capacity_reached",
    "capability_not_enabled",
    "connection_unavailable",
    "workspace_unavailable",
    "backend_not_supported",
    "local_device_required",
    "environment_changed",
    "provisioning_failed",
    "environment_expired",
]


class ConversationEnvironmentRefusal(BaseModel):
    """A controlled readiness outcome; permission failures remain HTTP errors."""

    code: ConversationEnvironmentRefusalCode
    message: str


class ConversationEnvironmentStart(BaseModel):
    """Ensure the environment selected by the caller's current published agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    project_execution_target: ProjectExecutionTarget | None = None


class ConversationEnvironmentRead(BaseModel):
    """Public lifecycle and control, never a CDP or workspace provider address."""

    id: UUID | None
    kind: ConversationEnvironmentKind
    execution_target: ProjectExecutionTarget
    agent_id: UUID
    state: ConversationEnvironmentState
    session_lifetime: Literal["run", "conversation"]
    idle_seconds: int = Field(ge=60, le=86400)
    control: ConversationEnvironmentControl
    can_control: bool
    expires_at: datetime | None
    refusal: ConversationEnvironmentRefusal | None


class ConversationEnvironmentList(BaseModel):
    """The browser and desktop available to this chat and selected agent."""

    items: list[ConversationEnvironmentRead]
