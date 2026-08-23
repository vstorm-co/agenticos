"""When an agent runs without anyone writing to it - one row per trigger.

Today an agent answers only when a person sends it something. A trigger is the
other way in: a stored rule that fires the same agent on its own, through the
same run path (:meth:`app.services.agent_runner.AgentRunnerService.execute`), so
budgets, approvals and accounting behave identically to a chat run.

Like :class:`app.db.models.agent_exposure.AgentExposure`, a trigger is operational
state, not part of what the agent *is*: you add, disable and remove one without
minting an agent version, and publishing a new version must not silently change
what is scheduled. That is why it is a row here and not a field on
:class:`app.agents.spec.AgentSpec` - the spec is exported and reused across
organizations, and a trigger carries two things that cannot travel with it: a
subject (`created_by_user_id`, the member a fired run runs as) and
deployment-local runtime state (`next_fire_at`, `last_run_id`, the run-log
conversation).

A row is one of two kinds, told apart by :class:`TriggerType`. Both fire the
agent through the one run path; they differ only in *what makes a fire due*:

* A **schedule** (`trigger_type = schedule`) fires on the clock - an
  `interval` ("every N seconds") or a `cron` expression ("daily/weekly at
  HH:MM", or any raw crontab, evaluated in UTC), told apart by
  :class:`ScheduleKind`. It carries a `next_fire_at` the heartbeat claims.
* An **event** (`trigger_type = event`) fires when something arrives - a GitHub
  issue, an inbound email (:class:`EventSource`) - delivered as a signed webhook
  the platform verifies against a per-trigger secret sealed in the vault. It has
  no `next_fire_at`: nothing is due until an event lands, so it never appears in
  the heartbeat's claim.

`schedule` and `event` are the internal names; the product calls them "Schedule"
and "Trigger". The `ck_trigger_shape` CHECK is what keeps a row honestly one kind
or the other - a schedule with its one cadence field and a next fire and no event
source, or an event with a source and none of the schedule machinery - so "why
would this fire" always has exactly one answer.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# The floor a trigger's interval cannot go below. The heartbeat ticks once a
# minute, so a shorter interval could not be honoured anyway - and it bounds the
# worst case a fat-fingered value reaches.
MIN_INTERVAL_SECONDS = 60


class TriggerType(enum.StrEnum):
    """The two ways a trigger becomes due.

    `SCHEDULE` fires on the clock and carries a `next_fire_at` the heartbeat
    claims. `EVENT` fires when something arrives and carries an `event_source`
    instead - it never has a next fire, so the heartbeat never sees it. The
    product calls these "Schedule" and "Trigger"; the code keeps one table and
    this discriminator.
    """

    SCHEDULE = "schedule"
    EVENT = "event"


class ScheduleKind(enum.StrEnum):
    """How a *schedule* trigger decides it is due.

    `INTERVAL` is "every N seconds since the last fire". `CRON` is a crontab
    expression evaluated in UTC - "daily at 09:00" is `0 9 * * *` - which the
    service computes the next fire for with croniter. UTC keeps a schedule
    surviving a restart without a stored timezone to reason about; a caller who
    means a local hour converts it when building the expression.

    Only meaningful when `trigger_type = schedule`; an event trigger leaves it at
    its default and the shape CHECK ignores it.
    """

    INTERVAL = "interval"
    CRON = "cron"


class EventSource(enum.StrEnum):
    """Where an *event* trigger's fire comes from.

    `GITHUB` is a repository webhook (an issue opened, verified by GitHub's
    `X-Hub-Signature-256` HMAC). The other two arrive through whatever relay
    the user already has - an inbound-mail parser, a Zapier/Make code step,
    their own script - as a JSON POST signed with the trigger's secret:
    `EMAIL` is an inbound message and `WEBHOOK` ("API" in the product's
    vocabulary) the catch-all for anything else that can send signed JSON. All
    three reach the one match-then-fire path; adding a fourth source is a value
    here, a branch in :mod:`app.services.trigger_events`, and one line in the
    vocabulary CHECK - nothing else on the row. A source earns its entry by
    being more than a renamed filter: `linkedin` was removed for differing
    from `WEBHOOK` in two field names and a promise no user-level API exists
    to keep.

    **`GMAIL` replaced an `email` source that was the same defect.** It named
    itself after a mailbox and then asked the user to run a relay - an inbound
    parser, a Zapier code step, their own script - that POSTs signed JSON at us,
    which is `WEBHOOK` with two renamed filter fields and the word *email* on a
    promise nothing here could keep: `app/services/email/` is send-only. `GMAIL`
    is delivered by *polling* a connected mailbox, so it has no inbound door and
    no per-trigger secret at all (#1068).
    """

    GITHUB = "github"
    GMAIL = "gmail"
    WEBHOOK = "webhook"


class AgentTrigger(Base, TimestampMixin):
    """One schedule that fires one agent."""

    __tablename__ = "agent_triggers"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The subject a fired run runs as. SET NULL, like the exposure's creator:
    # deleting the user must not delete the schedule's history. A null creator is
    # not licence to run as nobody - it is a trigger that can no longer be
    # attributed, so the claim query requires it non-null and the row is disabled
    # the next time it is inspected.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Turned off without being forgotten - the exposure's rationale exactly. Set
    # false when a creator loses access to the agent, so a schedule nobody can run
    # stops rather than retrying against a wall for ever.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # A human label for this trigger, shown where it is listed away from a form.
    # Optional: null falls back to the agent's name, so an existing row and a
    # "just schedule it" without a title both still read sensibly in every list.
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Which named environment's version this fires, like an exposure. SET NULL
    # keeps a schedule firing the default version rather than going silent when a
    # dev environment is removed.
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Which of the two concepts this row is. `schedule` fires on the clock and
    # fills the cadence columns below; `event` fires on arrival and fills the
    # event columns instead. The CHECK keeps a row to exactly one shape.
    trigger_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TriggerType.SCHEDULE.value
    )

    schedule_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ScheduleKind.INTERVAL.value
    )
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # An event trigger's source (`github`, `email`) and its per-source filter -
    # which repository, which sender - matched against the delivered payload
    # before firing. `event_config` is never null so the match code always has a
    # dict; a schedule leaves it `{}` and the source null.
    event_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    event_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # The secret an event webhook is verified against, sealed for this
    # organization through the one vault (`app/core/vault.py`) - GitHub's HMAC key
    # or the email relay's signing secret. Stored inline like a channel bot's
    # signing secret, with the master-key version that sealed it so a staged
    # rotation knows which key to unwrap with. Null on a schedule, which is never
    # reached over the wire.
    event_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The input each fire sends. A triggered run has no human turn, so the message
    # the agent answers is stored here; an event fire appends the payload's
    # rendered context to it so the agent knows which issue or email set it off.
    prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # When a *schedule* is next due. The heartbeat's claim query is
    # `is_active AND created_by_user_id IS NOT NULL AND next_fire_at <= now()`,
    # taken FOR UPDATE SKIP LOCKED; the flow advances it under that lock before
    # dispatching, so two ticks cannot fire one trigger. Null on an event trigger,
    # which the same `<= now` comparison then excludes without a special case:
    # nothing is due until an event arrives.
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The run the last fire opened. The no-overlap guard reads its status: a fire
    # is skipped while this names a run that has not reached a terminal state. SET
    # NULL so pruning a run does not delete the schedule; a null reads as "no fire
    # yet, or the last run was pruned" - both "not running".
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Set by the claim in the same UPDATE that advances `next_fire_at`, cleared by the
    # fired run in a `finally`. The no-overlap guard reads `last_run_id`, but that is
    # written only when `execute` returns - so for the whole time a run executes it
    # still names the *previous* (terminal) run, and a run slower than its interval
    # would fire on top of itself. This marker closes that window: a trigger with it
    # set is in flight and is not re-claimed. Bounded by a lease (`FIRE_LEASE` in the
    # repo) so a child that died without clearing it un-wedges rather than parking the
    # schedule for ever.
    fire_in_flight_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # The single run-log conversation every fire appends to. Opened when the
    # trigger is created (a per-fire conversation would be ~1440 rows a day on
    # the interval floor) and reused after. SET NULL so deleting the
    # conversation reopens a fresh log on the next fire rather than losing the
    # schedule.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # How an event trigger was set up, when it came from a portal preset rather
    # than the raw source picker. All nullable: every schedule, and every
    # hand-wired event trigger, leaves them null and behaves exactly as before -
    # these only carry the portal lineage and the provider-side registration.
    #
    # `connection_id` is the connected account whose token registered the webhook
    # (and, being an MCP connection, also powers the agent's tools). SET NULL so
    # disconnecting the account leaves the trigger firing on the hook that already
    # exists, marked orphaned rather than deleted. `provider_webhook_id` is the
    # hook the provider handed back, kept so `delete` can deregister it.
    # `delivery_mode` records whether the platform registered the hook
    # (`auto_webhook`) or the user pasted it (`manual`); `portal_key` the portal
    # the preset came from, for display and adapter dispatch.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    delivery_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider_webhook_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The target the hook was registered against (a `owner/repo`), kept because
    # deregistering it on delete needs the target as well as the id - GitHub has
    # no delete-hook-by-id-alone. Null on a manual or schedule row.
    provider_target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    portal_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Declared here as well as in the migration: the integration tests build the
    # schema from the models, so a constraint stated only in the migration would
    # be absent from exactly the tests written to prove it rejects a row.
    __table_args__ = (
        CheckConstraint("trigger_type IN ('schedule', 'event')", name="ck_trigger_type"),
        CheckConstraint("schedule_kind IN ('interval', 'cron')", name="ck_trigger_schedule_kind"),
        CheckConstraint(
            "event_source IS NULL OR event_source IN ('github', 'gmail', 'webhook')",
            name="ck_trigger_event_source",
        ),
        # The discriminator across both concepts, in one constraint so a row can
        # never be a half-schedule-half-event. A schedule carries a next fire, one
        # cadence field (interval xor cron), and no event source; an event carries
        # a source, none of the schedule machinery, and a sealed secret *if and
        # only if* its source is one something POSTs to. So "why would this fire,
        # and how is it authenticated" always has one answer.
        #
        # The secret is conditional because a polled source has nothing to
        # authenticate: `gmail` is read from a connected mailbox, so a secret on
        # such a row is a credential nobody can spend and a URL nobody should be
        # given. Stated here rather than trusted to the service, because it was
        # the service that got it wrong - every event trigger minted a secret and
        # was born `manual`, so creating a Gmail trigger handed out a webhook URL
        # for a door that refuses it (#1068).
        CheckConstraint(
            "(trigger_type = 'schedule' AND next_fire_at IS NOT NULL "
            "AND event_source IS NULL "
            "AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL "
            "AND cron_expression IS NULL) "
            "OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL "
            "AND interval_seconds IS NULL))) "
            "OR (trigger_type = 'event' AND event_source IS NOT NULL "
            "AND ((event_source IN ('gmail') AND event_secret_encrypted IS NULL "
            "AND secret_key_version IS NULL) "
            "OR (event_source NOT IN ('gmail') AND event_secret_encrypted IS NOT NULL "
            "AND secret_key_version IS NOT NULL)) "
            "AND next_fire_at IS NULL AND interval_seconds IS NULL "
            "AND cron_expression IS NULL)",
            name="ck_trigger_shape",
        ),
        # The runaway floor. A NULL interval passes here because the shape
        # constraint above already forbids one on an interval schedule.
        CheckConstraint(
            f"interval_seconds IS NULL OR interval_seconds >= {MIN_INTERVAL_SECONDS}",
            name="ck_trigger_interval_floor",
        ),
        # An auto-registered hook must remember which account owns it, or `delete`
        # has no token to deregister it with and the provider keeps delivering to
        # a dead trigger. A manual row carries neither and passes.
        CheckConstraint(
            "provider_webhook_id IS NULL OR connection_id IS NOT NULL",
            name="ck_trigger_registered_hook_has_connection",
        ),
        # The claim query filters on `is_active` and `next_fire_at` together.
        Index("ix_agent_triggers_due", "is_active", "next_fire_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentTrigger(id={self.id}, agent_id={self.agent_id}, "
            f"type={self.trigger_type}, active={self.is_active})>"
        )
