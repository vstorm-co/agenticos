"""The wire shapes of a workflow's log alert rules."""

import enum
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import BaseSchema

MAX_RULES_PER_WORKFLOW = 25
"""The most rules one workflow holds: the worker counts each one's lines every minute."""

AlertWindow = Literal[5, 15, 30, 60, 240, 1440]


class LogAlertAudience(enum.StrEnum):
    """Who a rule's alert reaches, as an agent alert's audience names them."""

    ADMINS = "admins"
    """The organization's owners and admins, plus the deployment's app admins."""

    OWNER = "owner"
    """The workflow's owner."""

    CHOSEN = "chosen"
    """Exactly the members named in `user_ids`."""


class WorkflowLogAlertCreate(BaseSchema):
    """A rule: count the lines that match, and tell the audience when enough do."""

    name: str = Field(min_length=1, max_length=100)
    outcomes: list[str] = Field(
        min_length=1,
        max_length=20,
        description="The ports, or `error`, a line left by; a line counts when it left by any",
    )
    node_instance_id: UUID | None = Field(
        default=None, description="Only this step's lines; every step that logs when unset"
    )
    message_contains: str | None = Field(
        default=None, min_length=1, max_length=200, description="Text the message contains"
    )
    threshold: int = Field(ge=1, le=1000, description="How many occurrences fire the alert")
    window_minutes: AlertWindow = Field(description="The minutes back the lines are counted over")
    audience: list[LogAlertAudience] = Field(
        min_length=1, description="Who hears of it: roles, as an agent alert's audience"
    )
    user_ids: list[UUID] = Field(
        default_factory=list,
        max_length=50,
        description="Members to tell when `audience` includes `chosen`; ignored otherwise",
    )
    enabled: bool = True


class WorkflowLogAlertUpdate(BaseSchema):
    """Fields of a rule to change; the rest stay as they are."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    outcomes: list[str] | None = Field(default=None, min_length=1, max_length=20)
    node_instance_id: UUID | None = None
    message_contains: str | None = Field(default=None, min_length=1, max_length=200)
    threshold: int | None = Field(default=None, ge=1, le=1000)
    window_minutes: AlertWindow | None = None
    audience: list[LogAlertAudience] | None = Field(default=None, min_length=1)
    user_ids: list[UUID] | None = Field(default=None, max_length=50)
    enabled: bool | None = None

    @model_validator(mode="after")
    def _only_the_clearable_fields_take_null(self) -> Self:
        for field in self.model_fields_set - {"node_instance_id", "message_contains"}:
            if getattr(self, field) is None:
                raise ValueError(f"`{field}` cannot be null")
        return self


class WorkflowLogAlertFiringRead(BaseSchema):
    """One time a rule fired."""

    id: UUID
    fired_at: datetime
    count: int
    window_start: datetime


class WorkflowLogAlertRead(BaseSchema):
    """A rule, with its last alert."""

    id: UUID
    workflow_id: UUID
    name: str
    outcomes: list[str]
    node_instance_id: UUID | None
    message_contains: str | None
    threshold: int
    window_minutes: int
    audience: list[LogAlertAudience]
    user_ids: list[UUID]
    enabled: bool
    last_firing: WorkflowLogAlertFiringRead | None = None
    created_at: datetime
    updated_at: datetime | None


class WorkflowLogAlertList(BaseSchema):
    items: list[WorkflowLogAlertRead]
