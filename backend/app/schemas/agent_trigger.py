"""Schemas for agent triggers - a schedule or an event that fires an agent."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from croniter import CroniterBadDateError, croniter
from pydantic import ConfigDict, Field, computed_field, model_validator

from app.core.config import settings
from app.db.models.agent_trigger import MIN_INTERVAL_SECONDS, EventSource
from app.schemas.base import BaseSchema, TimestampSchema

# The interval floor is a database CHECK (`ck_trigger_interval_floor`); this
# ceiling is input-only, and its job is a 422 rather than a 500. `interval_seconds`
# is stored in a PostgreSQL `integer`, so a larger value overflows the column, and
# on the way there `_next_fire` feeds it to `timedelta`, which raises `OverflowError`
# past its own limit. Capping at the column's own ceiling refuses both before a row
# is touched; a cadence longer than 68 years is a cron expression's job anyway.
MAX_INTERVAL_SECONDS = 2_147_483_647


def _cron_has_next(expression: str) -> bool:
    """Whether a cron expression is valid *and* ever actually fires.

    `croniter.is_valid` checks only syntax, so `0 0 31 2 *` - the 31st of a
    February that never has one - passes it, and then `_cron_next` exhausts its
    forward search and raises `CroniterBadDateError`, turning a user's cadence
    into a 500 at create or retime time. Resolving one occurrence here proves the
    expression has a future, so an unschedulable one is refused as a 422 naming
    the field instead.

    Only the five-field crontab shape is accepted. croniter also parses a
    six-field expression with a seconds column, but the heartbeat that fires
    schedules ticks once a minute, so `* * * * * *` would be accepted promising
    once a second and then fire once a minute, permanently overdue - a cadence
    the platform cannot honour is refused rather than quietly rounded.
    """
    if len(expression.split()) != 5:
        return False
    if not croniter.is_valid(expression):
        return False
    try:
        croniter(expression).get_next()
    except CroniterBadDateError:
        return False
    return True


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


class GmailTriggerConfig(BaseSchema):
    """The filter a Gmail trigger applies to a message the poller read.

    All three are optional; absent, the trigger fires on every message that
    arrives in the connected mailbox. `label` is Gmail's own - `INBOX`,
    `IMPORTANT`, or a user label - which is how somebody narrows to a filtered
    slice of their mail without writing a substring for it. Unknown keys are
    refused for the same reason as the GitHub config.
    """

    model_config = ConfigDict(extra="forbid")

    subject_contains: str | None = Field(default=None, max_length=255)
    sender_contains: str | None = Field(default=None, max_length=255)
    label: str | None = Field(default=None, max_length=128)


class WebhookTriggerConfig(BaseSchema):
    """The generic webhook source carries no filter - a signed delivery fires.

    The catch-all for anything that can POST signed JSON. Filtering is the
    sender's job (it chose to deliver); an empty model rather than no model so an
    unknown key is still refused instead of stored to mean nothing.
    """

    model_config = ConfigDict(extra="forbid")


_EVENT_CONFIG_MODELS: dict[str, type[BaseSchema]] = {
    EventSource.GITHUB.value: GithubTriggerConfig,
    EventSource.GMAIL.value: GmailTriggerConfig,
    EventSource.WEBHOOK.value: WebhookTriggerConfig,
}


class TriggerCreate(BaseSchema):
    """A new trigger for the agent named in the path - a schedule or an event.

    `trigger_type` defaults to `schedule`, which is one of two cadences:
    `interval` ("every N seconds") or `cron` (a crontab evaluated in UTC), the
    expression parsed here so an unschedulable one is a 422 naming the field, not
    a fire that never comes. An `event` trigger instead names an `event_source`
    (`github`, `email`, or the catch-all `webhook`), an optional
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
    interval_seconds: int | None = Field(
        default=None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )
    cron_expression: str | None = Field(default=None, max_length=255)

    # Event fields.
    event_source: Literal["github", "gmail", "webhook"] | None = None
    event_config: dict[str, Any] | None = None
    event_secret: str | None = Field(default=None, min_length=16, max_length=255)

    # Portal preset path. When `portal_key`/`preset_key` are given, the service
    # resolves the preset for its `event_source` and mints the signing secret, so
    # the caller sends neither `event_source` nor `event_secret` - only which
    # portal and preset, the connected account whose token registers the webhook,
    # and the target (which repository) it points at. An `event_config` *is*
    # allowed here: it is the caller's per-source filter, merged over the preset's
    # defaults and validated server-side against the source the catalog resolves.
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
            if not _cron_has_next(self.cron_expression):
                raise ValueError(
                    "cron_expression is not a valid crontab expression that ever fires"
                )

    def _validate_event(self) -> None:
        # The preset path fills `event_source` and mints the secret from the
        # catalog, so those two are refused here; an `event_config` is allowed as
        # the caller's filter override and left for the service to merge and
        # validate against the source, which is unknown here until the catalog is
        # read. So its shape is checked here and the rest left to the service.
        if self.portal_key is not None or self.preset_key is not None:
            if self.portal_key is None or self.preset_key is None:
                raise ValueError("portal_key and preset_key must be given together")
            if self.event_source is not None or self.event_secret is not None:
                raise ValueError("event_source and event_secret come from the preset")
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


_UPDATE_NOT_NULLABLE = ("prompt", "is_active")


class TriggerUpdate(BaseSchema):
    """Pause, resume, retime, rename, or reword a trigger. All fields optional.

    A schedule's cadence can change in place: a new interval, a new cron, or a
    switch between the two (`schedule_kind` with its cadence field). The service
    resolves the pair, re-validates a cron and recomputes the next fire, so the
    columns the shape CHECK depends on stay consistent. An event trigger's *filter*
    can change in place too: `event_config` is re-validated against the source's
    typed model, so refiltering which issue actions fire is an edit rather than a
    delete-and-recreate. What still cannot change is a trigger's *type* - a
    schedule never becomes an event - nor an event's source or secret: repointing
    an event is a different trigger, made by deleting this one and creating that,
    so a cadence field on an event, or an `event_config` on a schedule, is refused.

    `None` means "not sent" for every field except `environment_id` and `name`,
    whose null is the deliberate "back to the default" - the default environment,
    the agent's own name. `prompt` and `is_active` map to NOT NULL columns, so an
    *explicit* null for one is refused here as a 422 rather than reaching the row
    as a 500 IntegrityError - the `exclude_unset` dump cannot tell a sent null from
    an unsent one, so the field must. `interval_seconds` is *not* in that set: the
    column is nullable (an event trigger and a cron schedule both leave it null),
    and an explicit null on an interval edit is already a clean refusal from the
    service's `_resolve_cadence`, which names the field rather than letting the
    shape CHECK 500.
    """

    prompt: str | None = Field(default=None, min_length=1, max_length=10000)
    name: str | None = Field(default=None, max_length=120)
    schedule_kind: Literal["interval", "cron"] | None = None
    interval_seconds: int | None = Field(
        default=None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )
    cron_expression: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    environment_id: UUID | None = None
    # An event trigger's filter. Re-validated against its source's typed model in
    # the service (which owns `event_source`), so an unknown key is refused there
    # rather than stored to match nothing; a schedule has no filter and one sent
    # for it is refused. The source and the secret are not editable here.
    event_config: dict[str, Any] | None = None

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
    # page). The service fills all three from the listing query's join onto
    # agents - the avatar pair so the row can draw the same face every other
    # surface draws, not just the name.
    agent_name: str | None = None
    agent_has_avatar: bool = False
    agent_avatar_color: int | None = None
    # Whether *this caller* may edit, delete or run-now this trigger - the same
    # creator-or-`agents:edit` rule the service's `_owned` enforces, resolved per
    # row and per agent so a control the caller cannot use is not rendered rather
    # than rendered and then 403'd. Defaults false: a surface that does not set it
    # (a raw model_validate) hides the controls, which is the safe direction.
    can_manage: bool = False
    # The trigger's own title, or null to fall back to the agent's name.
    name: str | None = None
    created_by_user_id: UUID | None = None
    is_active: bool
    environment_id: UUID | None = None
    trigger_type: Literal["schedule", "event"]
    schedule_kind: Literal["interval", "cron"]
    interval_seconds: int | None = None
    cron_expression: str | None = None
    event_source: Literal["github", "gmail", "webhook"] | None = None
    event_config: dict[str, Any] = Field(default_factory=dict)
    prompt: str
    # Null on an event trigger, which has no scheduled next fire.
    next_fire_at: datetime | None = None
    last_fired_at: datetime | None = None
    last_run_id: UUID | None = None
    conversation_id: UUID | None = None
    # The portal lineage, when this trigger came from a preset. `delivery_mode` is
    # `auto_webhook` when the platform registered the hook and `manual` when the
    # user pastes the URL below; every event trigger carries one - a raw event
    # trigger is `manual`, since nobody registered a hook for it - and only a
    # schedule leaves it null. `portal_key` is null on a schedule and on a raw
    # event trigger, which came from no preset.
    portal_key: str | None = None
    delivery_mode: Literal["auto_webhook", "manual", "polling"] | None = None
    connection_id: UUID | None = None
    # The target the webhook was registered against (a `owner/repo`), so a listing
    # can read "New issue in acme/repo" rather than just the source. Null on a
    # schedule, a manual trigger, or an auto one with no target chosen.
    provider_target: str | None = None

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

        **Null for a polled source too.** Nothing POSTs to a Gmail trigger - the
        door refuses a delivery naming one - so a URL here is an address that
        answers nothing, and the client showed it as "add this webhook URL to your
        provider" for a provider there is nothing to add it to (#1068).
        """
        if self.trigger_type != "event" or self.event_source is None:
            return None
        if self.delivery_mode == "polling":
            return None
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        return f"{base}/api/v1/webhooks/triggers/{self.event_source}/{self.id}"


class TriggerCreateRead(TriggerRead):
    """The create response - a `TriggerRead` that may carry the secret once.

    A preset mints the signing secret server-side, and for a `manual`-delivery
    portal (the platform did not register the webhook itself) the person setting
    it up needs that secret to sign their relay's deliveries. It is returned here
    exactly once, on create, and never again: `TriggerRead` - what every read and
    the listing serialize - has no such field, so a secret sealed in the vault is
    never re-exposed. Null on a schedule, on an auto-registered trigger (the
    platform holds the secret), and on a raw trigger (the caller chose it and
    already knows it).
    """

    reveal_secret: str | None = None


class TriggerList(BaseSchema):
    items: list[TriggerRead]
    total: int
