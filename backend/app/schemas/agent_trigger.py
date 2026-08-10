"""Schemas for agent triggers - a schedule that fires an agent."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.db.models.agent_trigger import MIN_INTERVAL_SECONDS
from app.schemas.base import BaseSchema, TimestampSchema


class TriggerCreate(BaseSchema):
    """A new schedule for the agent named in the path.

    `schedule_kind` defaults to `interval`. `cron` is accepted by the shape check
    here but refused by the service until the interval-first follow-up lands
    (agenticos#44), so a client learns the field exists without it half-working.
    """

    prompt: str = Field(min_length=1, max_length=10000)
    schedule_kind: Literal["interval", "cron"] = "interval"
    interval_seconds: int | None = Field(default=None, ge=MIN_INTERVAL_SECONDS)
    cron_expression: str | None = Field(default=None, max_length=255)
    environment_id: UUID | None = None

    @model_validator(mode="after")
    def _one_schedule(self) -> TriggerCreate:
        """Exactly the fields the chosen kind needs, and no others.

        The database CHECK says the same thing, but a request that trips it comes
        back as an unreadable IntegrityError; caught here it is a 422 naming the
        field that is wrong.
        """
        if self.schedule_kind == "interval":
            if self.interval_seconds is None:
                raise ValueError("interval_seconds is required for an interval schedule")
            if self.cron_expression is not None:
                raise ValueError("cron_expression is not valid for an interval schedule")
        else:
            if self.cron_expression is None:
                raise ValueError("cron_expression is required for a cron schedule")
            if self.interval_seconds is not None:
                raise ValueError("interval_seconds is not valid for a cron schedule")
        return self


class TriggerUpdate(BaseSchema):
    """Pause, resume, retime, repoint, or reword a schedule. All fields optional.

    `schedule_kind` cannot be changed here - switching an interval trigger to cron
    is a different schedule, made by deleting this one and creating that. Leaving
    it out keeps the discriminator and its columns consistent without a second
    validator to police a half-changed row.
    """

    prompt: str | None = Field(default=None, min_length=1, max_length=10000)
    interval_seconds: int | None = Field(default=None, ge=MIN_INTERVAL_SECONDS)
    is_active: bool | None = None
    environment_id: UUID | None = None


class TriggerRead(BaseSchema, TimestampSchema):
    id: UUID
    agent_id: UUID
    created_by_user_id: UUID | None = None
    is_active: bool
    environment_id: UUID | None = None
    schedule_kind: Literal["interval", "cron"]
    interval_seconds: int | None = None
    cron_expression: str | None = None
    prompt: str
    next_fire_at: datetime
    last_fired_at: datetime | None = None
    last_run_id: UUID | None = None
    conversation_id: UUID | None = None


class TriggerList(BaseSchema):
    items: list[TriggerRead]
    total: int
