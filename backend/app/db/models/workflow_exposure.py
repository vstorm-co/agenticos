"""The ways a workflow runs with nobody pressing Start (#1792).

A caller who is present - the HTTP API, a WebSocket, the console's chat - needs
no row: whoever may run the workflow starts it as themselves, on its live
version, and is checked at that moment. A door nobody stands at needs one. A
signed webhook and a schedule fire on their own, so each is a row here saying
which published version it runs and as whom.

Like :class:`app.db.models.agent_trigger.AgentTrigger`, an exposure is
operational state and not part of the graph: it is added, paused and removed
without publishing, and it carries what a graph cannot travel with - a
principal, a sealed secret, a clock. Unlike an agent's exposure it is **pinned**
to one `WorkflowVersion`: publishing must never change what a live webhook runs,
so moving an exposure to a newer version is its own explicit, audited write.
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


class ExposureScheduleKind(enum.StrEnum):
    """How a schedule becomes due: every N seconds, or a crontab evaluated in UTC."""

    INTERVAL = "interval"
    CRON = "cron"


class WorkflowExposure(Base, TimestampMixin):
    """One webhook or one schedule that runs one workflow's pinned version."""

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
        index=True,
    )
    # The version every fire runs - never re-resolved from the workflow's
    # current one. CASCADE only because a version goes when its workflow does.
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    adapter: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The member a fired run acts as: whoever created the row or last changed
    # it, since whoever decided it should run answers for what it does. Checked
    # afresh on every fire. SET NULL so deleting the account keeps the history;
    # a null principal is a row that can no longer fire, not licence to run as
    # nobody, and is disabled when it next comes due.
    execution_principal_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # What a schedule hands `core.input` as its payload - a clock has no body.
    # A webhook's payload is each delivery's own body, so this stays `{}`.
    run_input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # A webhook's HMAC key, sealed for the organization through the vault, and
    # the master-key version that sealed it. Null on a schedule.
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # A schedule's cadence - one of the two fields, told apart by the kind - and
    # when it is next due. Null on a webhook, which the heartbeat's
    # `next_fire_at <= now` claim then never selects.
    schedule_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(String(255), nullable=True)
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
        CheckConstraint("adapter IN ('webhook', 'schedule')", name="ck_workflow_exposure_adapter"),
        # One shape per adapter: a webhook has a sealed secret and none of the
        # clock; a schedule has exactly one cadence field and a next fire, and
        # no secret. So "why would this fire" always has one answer.
        CheckConstraint(
            "(adapter = 'webhook' AND secret_encrypted IS NOT NULL "
            "AND secret_key_version IS NOT NULL AND schedule_kind IS NULL "
            "AND interval_seconds IS NULL AND cron_expression IS NULL "
            "AND next_fire_at IS NULL) "
            "OR (adapter = 'schedule' AND secret_encrypted IS NULL "
            "AND secret_key_version IS NULL AND next_fire_at IS NOT NULL "
            "AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL "
            "AND cron_expression IS NULL) "
            "OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL "
            "AND interval_seconds IS NULL)))",
            name="ck_workflow_exposure_shape",
        ),
        CheckConstraint(
            f"interval_seconds IS NULL OR interval_seconds >= {MIN_INTERVAL_SECONDS}",
            name="ck_workflow_exposure_interval_floor",
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
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "exposure_id", "delivery_id", name="uq_workflow_webhook_delivery_exposure_delivery"
        ),
    )
