"""Schemas for agent triggers - a schedule or an event that fires an agent."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from croniter import croniter
from pydantic import ConfigDict, Field, computed_field, model_validator

from app.core.config import settings
from app.db.models.agent_trigger import MIN_INTERVAL_SECONDS, EventSource
from app.schemas.base import BaseSchema, TimestampSchema

# GitHub's `issues` webhook actions, so a typo like `opnened` is a 422 rather
# than a filter stored to match nothing. From GitHub's webhook-events reference.
GithubIssueAction = Literal[
    "opened",
    "edited",
    "deleted",
    "transferred",
    "pinned",
    "unpinned",
    "closed",
    "reopened",
    "assigned",
    "unassigned",
    "labeled",
    "unlabeled",
    "locked",
    "unlocked",
    "milestoned",
    "demilestoned",
]

_DEFAULT_GITHUB_ACTIONS: list[GithubIssueAction] = ["opened"]


class GithubTriggerConfig(BaseSchema):
    """The filter a GitHub event trigger applies to a delivered webhook.

    Only `issues` webhooks reach the fire path at all (the event type is read
    from the `X-GitHub-Event` header); `actions` narrows *which* issue actions
    fire, defaulting to issue creation. Both an unknown key and an action outside
    GitHub's own vocabulary are refused, so a mistyped filter is a 422, not one
    that silently never matches.
    """

    model_config = ConfigDict(extra="forbid")

    actions: list[GithubIssueAction] = Field(
        default_factory=lambda: list(_DEFAULT_GITHUB_ACTIONS), min_length=1
    )


class EmailTriggerConfig(BaseSchema):
    """The filter an email event trigger applies to a delivered message.

    Both filters are optional substrings; absent, the trigger fires on any signed
    message delivered to its address. Unknown keys are refused for the same reason
    as the GitHub config.
    """

    model_config = ConfigDict(extra="forbid")

    subject_contains: str | None = Field(default=None, max_length=255)
    sender_contains: str | None = Field(default=None, max_length=255)


class LinkedinTriggerConfig(BaseSchema):
    """The filter a LinkedIn event trigger applies to a delivered post.

    LinkedIn offers no user-level webhooks, so the delivery comes from whatever
    relay watches the feed - a Zapier/Make step, a monitoring tool - posting the
    fields it saw. Both filters are optional substrings over those fields;
    absent, any signed delivery fires.
    """

    model_config = ConfigDict(extra="forbid")

    author_contains: str | None = Field(default=None, max_length=255)
    text_contains: str | None = Field(default=None, max_length=255)


class WebhookTriggerConfig(BaseSchema):
    """The generic webhook source carries no filter - a signed delivery fires.

    The catch-all for anything that can POST signed JSON. Filtering is the
    sender's job (it chose to deliver); an empty model rather than no model so an
    unknown key is still refused instead of stored to mean nothing.
    """

    model_config = ConfigDict(extra="forbid")


_EVENT_CONFIG_MODELS: dict[str, type[BaseSchema]] = {
    EventSource.GITHUB.value: GithubTriggerConfig,
    EventSource.EMAIL.value: EmailTriggerConfig,
    EventSource.LINKEDIN.value: LinkedinTriggerConfig,
    EventSource.WEBHOOK.value: WebhookTriggerConfig,
}


class TriggerCreate(BaseSchema):
    """A new trigger for the agent named in the path - a schedule or an event.

    `trigger_type` defaults to `schedule`, which is one of two cadences:
    `interval` ("every N seconds") or `cron` (a crontab evaluated in UTC), the
    expression parsed here so an unschedulable one is a 422 naming the field, not
    a fire that never comes. An `event` trigger instead names an `event_source`
    (`github`, `email`, `linkedin`, or the catch-all `webhook`), an optional
    per-source `event_config` filter, and the `event_secret` its inbound webhook
    is signed with - the secret is sealed by the service and never stored or
    returned in the clear.
    """

    prompt: str = Field(min_length=1, max_length=10000)
    # An optional human title; null lists the trigger by its agent's name instead.
    name: str | None = Field(default=None, max_length=120)
    trigger_type: Literal["schedule", "event"] = "schedule"
    environment_id: UUID | None = None

    # Schedule fields.
    schedule_kind: Literal["interval", "cron"] = "interval"
    interval_seconds: int | None = Field(default=None, ge=MIN_INTERVAL_SECONDS)
    cron_expression: str | None = Field(default=None, max_length=255)

    # Event fields.
    event_source: Literal["github", "email", "linkedin", "webhook"] | None = None
    event_config: dict[str, Any] | None = None
    event_secret: str | None = Field(default=None, min_length=16, max_length=255)

    # Portal preset path. When `portal_key`/`preset_key` are given, the service
    # resolves the preset for its `event_source` and filter and mints the signing
    # secret, so the caller sends none of the event_* fields above - only which
    # portal and preset, the connected account whose token registers the webhook,
    # and the target (which repository) it points at.
    portal_key: str | None = Field(default=None, max_length=64)
    preset_key: str | None = Field(default=None, max_length=64)
    connection_id: UUID | None = None
    target: str | None = Field(default=None, max_length=255)

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
        # The preset path carries none of the event_* fields - the service fills
        # them from the preset and mints the secret - so its shape is checked here
        # and the rest is left to the service, which owns the catalog.
        if self.portal_key is not None or self.preset_key is not None:
            if self.portal_key is None or self.preset_key is None:
                raise ValueError("portal_key and preset_key must be given together")
            if (
                self.event_source is not None
                or self.event_secret is not None
                or self.event_config is not None
            ):
                raise ValueError("event_source, event_secret and event_config come from the preset")
            return
        if self.event_source is None:
            raise ValueError("event_source is required for an event trigger")
        if self.event_secret is None:
            raise ValueError("event_secret is required for an event trigger")
        # Normalise the filter through its source's typed model: fills defaults
        # (a GitHub trigger with no actions fires on issue creation) and refuses
        # an unknown key. `model_validate({})` cannot fail for any source.
        config_model = _EVENT_CONFIG_MODELS[self.event_source]
        self.event_config = config_model.model_validate(self.event_config or {}).model_dump()

    def _reject_event_fields(self) -> None:
        if self.event_source is not None:
            raise ValueError("event_source is not valid for a schedule")
        if self.event_secret is not None:
            raise ValueError("event_secret is not valid for a schedule")
        if self.event_config is not None:
            raise ValueError("event_config is not valid for a schedule")
        if self.portal_key is not None or self.preset_key is not None:
            raise ValueError("a portal preset is not valid for a schedule")
        if self.connection_id is not None:
            raise ValueError("connection_id is not valid for a schedule")
        if self.target is not None:
            raise ValueError("target is not valid for a schedule")

    def _reject_schedule_fields(self) -> None:
        if self.interval_seconds is not None:
            raise ValueError("interval_seconds is not valid for an event trigger")
        if self.cron_expression is not None:
            raise ValueError("cron_expression is not valid for an event trigger")


_UPDATE_NOT_NULLABLE = ("prompt", "interval_seconds", "is_active")


class TriggerUpdate(BaseSchema):
    """Pause, resume, retime, rename, or reword a trigger. All fields optional.

    A schedule's cadence can change in place: a new interval, a new cron, or a
    switch between the two (`schedule_kind` with its cadence field). The service
    resolves the pair, re-validates a cron and recomputes the next fire, so the
    columns the shape CHECK depends on stay consistent. What still cannot change is
    a trigger's *type* - a schedule never becomes an event - nor an event's source,
    filter or secret: repointing an event is a different trigger, made by deleting
    this one and creating that, so a cadence field on an event is refused.

    `None` means "not sent" for every field except `environment_id` and `name`,
    whose null is the deliberate "back to the default" - the default environment,
    the agent's own name. `prompt`, `interval_seconds` and `is_active` map to NOT
    NULL columns, so an *explicit* null for one is refused here as a 422 rather than
    reaching the row as a 500 IntegrityError - the `exclude_unset` dump cannot tell
    a sent null from an unsent one, so the field must.
    """

    prompt: str | None = Field(default=None, min_length=1, max_length=10000)
    name: str | None = Field(default=None, max_length=120)
    schedule_kind: Literal["interval", "cron"] | None = None
    interval_seconds: int | None = Field(default=None, ge=MIN_INTERVAL_SECONDS)
    cron_expression: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    environment_id: UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null(cls, data: Any) -> Any:
        """Refuse an explicit null for a field that maps to a NOT NULL column.

        Read on the raw input, not the resolved value, so it fires only for a key
        that is *present and null* - the one thing `exclude_unset` cannot later
        tell apart from an omitted field. `environment_id` is absent on purpose:
        its null is the deliberate "back to the default".
        """
        if isinstance(data, dict):
            for field in _UPDATE_NOT_NULLABLE:
                if field in data and data[field] is None:
                    raise ValueError(f"{field} cannot be set to null")
        return data


class TriggerRead(BaseSchema, TimestampSchema):
    id: UUID
    agent_id: UUID
    # Set only on the org-wide listing, where a row is shown away from its agent
    # and needs to name it; the per-agent list leaves it unset (the agent is the
    # page). The service fills it from the listing query's join onto agents.
    agent_name: str | None = None
    # The trigger's own title, or null to fall back to the agent's name.
    name: str | None = None
    created_by_user_id: UUID | None = None
    is_active: bool
    environment_id: UUID | None = None
    trigger_type: Literal["schedule", "event"]
    schedule_kind: Literal["interval", "cron"]
    interval_seconds: int | None = None
    cron_expression: str | None = None
    event_source: Literal["github", "email", "linkedin", "webhook"] | None = None
    event_config: dict[str, Any] = Field(default_factory=dict)
    prompt: str
    # Null on an event trigger, which has no scheduled next fire.
    next_fire_at: datetime | None = None
    last_fired_at: datetime | None = None
    last_run_id: UUID | None = None
    conversation_id: UUID | None = None
    # The portal lineage, when this trigger came from a preset. `delivery_mode` is
    # `auto_webhook` when the platform registered the hook and `manual` when the
    # user pastes the URL below; null on a schedule and on a raw event trigger.
    portal_key: str | None = None
    delivery_mode: Literal["auto_webhook", "manual"] | None = None
    connection_id: UUID | None = None

    @computed_field  # type: ignore[prop-decorator]  - pydantic reads the property
    @property
    def webhook_url(self) -> str | None:
        """Where an event trigger's provider must deliver, or null for a schedule.

        The full URL the caller pastes into GitHub or a relay, built on the
        deployment's one public address - `PUBLIC_BASE_URL`, the same setting
        channel webhooks, embeds and OAuth callbacks are built from. It is *not*
        derived from the browser's origin: the webhook is served by the API host
        (`api.<domain>`), which is a different origin from the dashboard, so a
        client that prepended its own origin would hand the provider a URL that
        404s. The secret that authenticates a delivery is never part of it.
        """
        if self.trigger_type != "event" or self.event_source is None:
            return None
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        return f"{base}/api/v1/webhooks/triggers/{self.event_source}/{self.id}"


class TriggerList(BaseSchema):
    items: list[TriggerRead]
    total: int
