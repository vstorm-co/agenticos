"""Schemas for agent triggers - a schedule or an event that fires an agent."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from croniter import croniter
from pydantic import ConfigDict, Field, computed_field, model_validator

from app.db.models.agent_trigger import MIN_INTERVAL_SECONDS, EventSource
from app.schemas.base import BaseSchema, TimestampSchema


class GithubTriggerConfig(BaseSchema):
    """The filter a GitHub event trigger applies to a delivered webhook.

    Only `issues` webhooks reach the fire path at all (the event type is read
    from the `X-GitHub-Event` header); `actions` narrows *which* issue actions
    fire, defaulting to issue creation. Unknown keys are refused so a mistyped
    filter is a 422, not a filter that silently never matches.
    """

    model_config = ConfigDict(extra="forbid")

    actions: list[str] = Field(default_factory=lambda: ["opened"], min_length=1)


class EmailTriggerConfig(BaseSchema):
    """The filter an email event trigger applies to a delivered message.

    Both filters are optional substrings; absent, the trigger fires on any signed
    message delivered to its address. Unknown keys are refused for the same reason
    as the GitHub config.
    """

    model_config = ConfigDict(extra="forbid")

    subject_contains: str | None = Field(default=None, max_length=255)
    sender_contains: str | None = Field(default=None, max_length=255)


_EVENT_CONFIG_MODELS: dict[str, type[BaseSchema]] = {
    EventSource.GITHUB.value: GithubTriggerConfig,
    EventSource.EMAIL.value: EmailTriggerConfig,
}


class TriggerCreate(BaseSchema):
    """A new trigger for the agent named in the path - a schedule or an event.

    `trigger_type` defaults to `schedule`, which is one of two cadences:
    `interval` ("every N seconds") or `cron` (a crontab evaluated in UTC), the
    expression parsed here so an unschedulable one is a 422 naming the field, not
    a fire that never comes. An `event` trigger instead names an `event_source`
    (`github`, `email`), an optional per-source `event_config` filter, and the
    `event_secret` its inbound webhook is signed with - the secret is sealed by
    the service and never stored or returned in the clear.
    """

    prompt: str = Field(min_length=1, max_length=10000)
    trigger_type: Literal["schedule", "event"] = "schedule"
    environment_id: UUID | None = None

    # Schedule fields.
    schedule_kind: Literal["interval", "cron"] = "interval"
    interval_seconds: int | None = Field(default=None, ge=MIN_INTERVAL_SECONDS)
    cron_expression: str | None = Field(default=None, max_length=255)

    # Event fields.
    event_source: Literal["github", "email"] | None = None
    event_config: dict[str, Any] | None = None
    event_secret: str | None = Field(default=None, min_length=16, max_length=255)

    @model_validator(mode="after")
    def _shape(self) -> TriggerCreate:
        """Exactly the fields the chosen kind needs, and nothing from the other.

        The database CHECK (`ck_trigger_shape`) says the same thing about the
        columns, but a request that trips it comes back as an unreadable
        IntegrityError; caught here it is a 422 naming the field that is wrong.
        Two things the CHECK cannot judge are settled here as well: a cron
        expression is only parseable by croniter, and an event's `event_config` is
        normalised against its source's typed filter so an unknown key is refused
        rather than stored to match nothing.
        """
        if self.trigger_type == "schedule":
            self._reject_event_fields()
            self._validate_schedule()
        else:
            self._reject_schedule_fields()
            self._validate_event()
        return self

    def _validate_schedule(self) -> None:
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
            if not croniter.is_valid(self.cron_expression):
                raise ValueError("cron_expression is not a valid crontab expression")

    def _validate_event(self) -> None:
        if self.event_source is None:
            raise ValueError("event_source is required for an event trigger")
        if self.event_secret is None:
            raise ValueError("event_secret is required for an event trigger")
        # Normalise the filter through its source's typed model: fills defaults
        # (a GitHub trigger with no actions fires on issue creation) and refuses
        # an unknown key. `model_validate({})` cannot fail for either source.
        config_model = _EVENT_CONFIG_MODELS[self.event_source]
        self.event_config = config_model.model_validate(self.event_config or {}).model_dump()

    def _reject_event_fields(self) -> None:
        if self.event_source is not None:
            raise ValueError("event_source is not valid for a schedule")
        if self.event_secret is not None:
            raise ValueError("event_secret is not valid for a schedule")
        if self.event_config is not None:
            raise ValueError("event_config is not valid for a schedule")

    def _reject_schedule_fields(self) -> None:
        if self.interval_seconds is not None:
            raise ValueError("interval_seconds is not valid for an event trigger")
        if self.cron_expression is not None:
            raise ValueError("cron_expression is not valid for an event trigger")


class TriggerUpdate(BaseSchema):
    """Pause, resume, retime, repoint, or reword a trigger. All fields optional.

    What cannot change here is a trigger's shape: neither `schedule_kind` nor
    `trigger_type`, nor an event's source, filter or secret. Switching a schedule
    to cron, or repointing an event at a different repository, is a different
    trigger - made by deleting this one and creating that - so the columns the
    shape CHECK depends on stay consistent without a second validator policing a
    half-changed row. `interval_seconds` is accepted only for interval schedules;
    the service refuses it on a cron schedule or an event trigger.
    """

    prompt: str | None = Field(default=None, min_length=1, max_length=10000)
    interval_seconds: int | None = Field(default=None, ge=MIN_INTERVAL_SECONDS)
    is_active: bool | None = None
    environment_id: UUID | None = None


class TriggerRead(BaseSchema, TimestampSchema):
    id: UUID
    agent_id: UUID
    # Set only on the org-wide listing, where a row is shown away from its agent
    # and needs to name it; the per-agent list leaves it unset (the agent is the
    # page). The service fills it from the listing query's join onto agents.
    agent_name: str | None = None
    created_by_user_id: UUID | None = None
    is_active: bool
    environment_id: UUID | None = None
    trigger_type: Literal["schedule", "event"]
    schedule_kind: Literal["interval", "cron"]
    interval_seconds: int | None = None
    cron_expression: str | None = None
    event_source: Literal["github", "email"] | None = None
    event_config: dict[str, Any] = Field(default_factory=dict)
    prompt: str
    # Null on an event trigger, which has no scheduled next fire.
    next_fire_at: datetime | None = None
    last_fired_at: datetime | None = None
    last_run_id: UUID | None = None
    conversation_id: UUID | None = None

    @computed_field  # type: ignore[prop-decorator]  - pydantic reads the property
    @property
    def webhook_path(self) -> str | None:
        """Where an event trigger's provider must deliver, or null for a schedule.

        Derived from the source and id rather than stored, so it is correct
        wherever a row is serialized. The full URL is this path under the
        deployment's public origin, which the client already knows; the secret
        that authenticates a delivery is never part of it.
        """
        if self.trigger_type != "event" or self.event_source is None:
            return None
        return f"/api/v1/webhooks/triggers/{self.event_source}/{self.id}"


class TriggerList(BaseSchema):
    items: list[TriggerRead]
    total: int
