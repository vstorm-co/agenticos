"""The ways a workflow runs with nobody pressing Start (#1792).

A caller who is present - the HTTP API, a WebSocket, the console's chat - needs
no row: whoever may run the workflow starts it as themselves, on its live
version, and is checked at that moment. A door nobody stands at needs one. A
signed webhook, a GitHub repository's events, a schedule, a public form and a
channel bot's messages and a mailbox fire on their own, so each is a row here saying which published version it runs and as
whom.

The graph says *that* a workflow starts from a webhook or a schedule - its
trigger node - and an exposure is that node switched on: what a graph cannot
travel with, a principal, a sealed secret, a clock. Publishing writes it
(`app.services.workflow_triggers`): the new version takes the row over, runs as
the member who published it, and a trigger the new version no longer has is
removed. A workflow has one trigger, so it has at most one exposure, and the
row is kept across versions while its node is - a webhook's address and secret
survive a publish. Pausing is the one change made beside the graph.
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# The floor a schedule's interval cannot go below: the heartbeat ticks once a
# minute, so a shorter one could not be honoured. The agent trigger's floor.
MIN_INTERVAL_SECONDS = 60


class ExposureAdapter(enum.StrEnum):
    """Which unattended door this row is. Each value is a `WorkflowRun.triggered_by`."""

    WEBHOOK = "webhook"
    SCHEDULE = "schedule"
    FORM = "form"
    CHANNEL = "channel"
    GITHUB = "github"
    GMAIL = "gmail"


class ExposureScheduleKind(enum.StrEnum):
    """How a schedule becomes due: every N seconds, or a crontab evaluated in UTC."""

    INTERVAL = "interval"
    CRON = "cron"


class WorkflowExposure(Base, TimestampMixin):
    """One webhook, GitHub hook, schedule, form or bot that runs one workflow's pinned version."""

    __tablename__ = "workflow_exposures"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The version every fire runs - never re-resolved from the workflow's
    # current one. CASCADE only because a version goes when its workflow does.
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The trigger node this row switches on. A publish whose trigger is another
    # node - one deleted and re-added - replaces the row, and its address.
    node_instance_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    adapter: Mapped[str] = mapped_column(String(16), nullable=False)
    # The member a fired run acts as: whoever published the version it runs,
    # since whoever decided it should run answers for what it does. Checked
    # afresh on every fire. SET NULL so deleting the account keeps the history;
    # a null principal is a row that can no longer fire, not licence to run as
    # nobody, and is disabled when it next comes due.
    execution_principal_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # The input a schedule starts every run with, from its node's configuration
    # - a clock has no body. A webhook's is each delivery's own, so this stays `{}`.
    run_input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # A webhook's or a GitHub hook's HMAC key, sealed for the organization through
    # the vault, and the master-key version that sealed it. Null on the others.
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # A form's public address: the link is its only credential, kept across
    # publishes and replaced only when an editor asks for a new one.
    form_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    # The bot whose messages a channel trigger takes. SET NULL so deleting the
    # bot keeps the row's history; a row with no bot hears nothing.
    channel_bot_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("channel_bots.id", ondelete="SET NULL"),
        nullable=True,
    )

    # A GitHub hook the publish registered through the organization's connected
    # account: the connection it used, the repository and GitHub's id for the
    # hook, so a later publish or a removal can take it down. All null on a hook
    # somebody pasted in by hand.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_webhook_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # A schedule's cadence - one of the two fields, told apart by the kind - and
    # when it is next due. Null on a webhook, which the heartbeat's
    # `next_fire_at <= now` claim then never selects.
    schedule_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(String(255), nullable=True)
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The workflow's timezone, copied here when the schedule is published and when
    # the setting changes: a cron expression is read in it.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )

    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The run the last fire admitted. A schedule skips a tick while it is still
    # live, so a run slower than its interval does not stack up behind itself.
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Declared here as well as in the migration: the integration tests build the
    # schema from the models.
    __table_args__ = (
        UniqueConstraint("workflow_id", name="uq_workflow_exposure_workflow"),
        CheckConstraint(
            "adapter IN ('webhook', 'schedule', 'form', 'channel', 'github', 'gmail')",
            name="ck_workflow_exposure_adapter",
        ),
        # One shape per adapter: a webhook has a sealed secret and none of the
        # clock; a schedule has exactly one cadence field and a next fire, and
        # no secret; a form has its link and neither. So "why would this fire"
        # always has one answer.
        CheckConstraint(
            "(adapter IN ('webhook', 'github') AND secret_encrypted IS NOT NULL "
            "AND secret_key_version IS NOT NULL AND schedule_kind IS NULL "
            "AND interval_seconds IS NULL AND cron_expression IS NULL "
            "AND next_fire_at IS NULL AND form_token IS NULL AND channel_bot_id IS NULL) "
            "OR (adapter = 'schedule' AND secret_encrypted IS NULL "
            "AND secret_key_version IS NULL AND next_fire_at IS NOT NULL "
            "AND form_token IS NULL AND channel_bot_id IS NULL "
            "AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL "
            "AND cron_expression IS NULL) "
            "OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL "
            "AND interval_seconds IS NULL))) "
            "OR (adapter = 'form' AND form_token IS NOT NULL AND channel_bot_id IS NULL "
            "AND secret_encrypted IS NULL AND secret_key_version IS NULL "
            "AND schedule_kind IS NULL AND interval_seconds IS NULL "
            "AND cron_expression IS NULL AND next_fire_at IS NULL) "
            "OR (adapter IN ('channel', 'gmail') AND form_token IS NULL "
            "AND secret_encrypted IS NULL AND secret_key_version IS NULL "
            "AND schedule_kind IS NULL AND interval_seconds IS NULL "
            "AND cron_expression IS NULL AND next_fire_at IS NULL "
            "AND (adapter = 'channel' OR channel_bot_id IS NULL))",
            name="ck_workflow_exposure_shape",
        ),
        CheckConstraint(
            f"interval_seconds IS NULL OR interval_seconds >= {MIN_INTERVAL_SECONDS}",
            name="ck_workflow_exposure_interval_floor",
        ),
        # A bot's messages start one workflow at most.
        Index(
            "uq_workflow_exposure_channel_bot",
            "channel_bot_id",
            unique=True,
            postgresql_where="adapter = 'channel' AND channel_bot_id IS NOT NULL",
        ),
        # The heartbeat's claim: active schedules by when they are due.
        Index(
            "ix_workflow_exposure_due",
            "next_fire_at",
            postgresql_where="is_active AND next_fire_at IS NOT NULL",
        ),
    )


class WorkflowWebhookDelivery(Base):
    """One webhook delivery that was admitted, and the run it admitted.

    Written in the transaction that creates the run, so the claim on a delivery
    id and the run's existence commit together or not at all. The unique
    constraint is what makes a provider's retry of the same delivery answer with
    the first run instead of admitting a second - durable, unlike the agent
    trigger's short-lived Redis claim, because a duplicated workflow run repeats
    real side effects.
    """

    __tablename__ = "workflow_webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exposure_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_exposures.id", ondelete="CASCADE"),
        nullable=False,
    )
    delivery_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Historical identity survives content retention; the exposure and tenant
    # remain the owners that delete the delivery tombstone.
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "exposure_id", "delivery_id", name="uq_workflow_webhook_delivery_exposure_delivery"
        ),
    )
