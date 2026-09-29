"""Workflow exposure schemas - a workflow's webhooks and schedules (#1792)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, computed_field, model_validator

from app.core.config import settings
from app.db.models.workflow_exposure import (
    MIN_INTERVAL_SECONDS,
    ExposureAdapter,
    ExposureScheduleKind,
)
from app.schemas.agent_trigger import MAX_INTERVAL_SECONDS, _cron_has_next
from app.schemas.base import BaseSchema, TimestampSchema


class _Cadence(BaseSchema):
    """A schedule's cadence fields, shared by create and update."""

    schedule_kind: ExposureScheduleKind | None = None
    interval_seconds: int | None = Field(
        default=None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )
    cron_expression: str | None = Field(default=None, max_length=255)

    def _check_cadence(self) -> None:
        """Exactly the kind's own field - the shape the database CHECK wants,
        refused here as a 422 naming the field rather than an IntegrityError."""
        if self.schedule_kind is ExposureScheduleKind.INTERVAL:
            if self.interval_seconds is None or self.cron_expression is not None:
                raise ValueError("an interval schedule takes interval_seconds and no cron")
        elif self.schedule_kind is ExposureScheduleKind.CRON:
            if self.cron_expression is None or self.interval_seconds is not None:
                raise ValueError("a cron schedule takes cron_expression and no interval")
            if not _cron_has_next(self.cron_expression):
                raise ValueError(
                    "cron_expression is not a valid crontab expression that ever fires"
                )
        elif self.interval_seconds is not None or self.cron_expression is not None:
            raise ValueError("a cadence needs its schedule_kind")


class WorkflowExposureCreate(_Cadence):
    """A new webhook or schedule on a workflow's current published version.

    A webhook takes only a name - each delivery's body is its run's input, and
    its signing secret is minted by the server and returned once. A schedule
    takes a cadence and the input every fire starts with.
    """

    adapter: ExposureAdapter
    name: str | None = Field(default=None, max_length=120)
    run_input: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _shape(self) -> WorkflowExposureCreate:
        if self.adapter is ExposureAdapter.WEBHOOK:
            if self.schedule_kind is not None or self.run_input:
                raise ValueError("a webhook takes no cadence and no input")
        elif self.schedule_kind is None:
            raise ValueError("a schedule needs a schedule_kind")
        self._check_cadence()
        return self


class WorkflowExposureUpdate(_Cadence):
    """Pause, rename, retime or re-input an exposure, or move it to the live version.

    Every field is optional; a cadence change sends `schedule_kind` with its one
    field. `pin_current_version` moves the exposure to the workflow's current
    published version - the only way what an exposure runs ever changes.
    """

    name: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None
    run_input: dict[str, Any] | None = None
    pin_current_version: bool = False

    @model_validator(mode="after")
    def _shape(self) -> WorkflowExposureUpdate:
        self._check_cadence()
        return self


class WorkflowExposureRead(BaseSchema, TimestampSchema):
    id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    version_number: int
    adapter: ExposureAdapter
    name: str | None
    is_active: bool
    execution_principal_user_id: UUID | None
    run_input: dict[str, Any]
    schedule_kind: ExposureScheduleKind | None
    interval_seconds: int | None
    cron_expression: str | None
    next_fire_at: datetime | None
    last_fired_at: datetime | None
    last_run_id: UUID | None

    @computed_field  # type: ignore[prop-decorator]  - pydantic reads the property
    @property
    def webhook_url(self) -> str | None:
        """Where a webhook's sender delivers, on the deployment's public address.

        Built on `PUBLIC_BASE_URL` for the reason `TriggerRead.webhook_url` gives:
        the API host is a different origin from the console, so a URL built from
        the browser's would 404. Null for a schedule, which nothing POSTs to.
        """
        if self.adapter is not ExposureAdapter.WEBHOOK:
            return None
        return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/workflow-webhooks/{self.id}"


class WorkflowExposureCreated(WorkflowExposureRead):
    """The create and rotate response: a webhook's signing secret, this once.

    `WorkflowExposureRead` - every read and the listing - has no such field, so
    a secret sealed in the vault is never exposed again. Null for a schedule.
    """

    reveal_secret: str | None = None


class WorkflowExposureList(BaseSchema):
    items: list[WorkflowExposureRead]


class WebhookAdmitted(BaseSchema):
    """What a webhook delivery is answered with: the run it admitted.

    `duplicate` is true when this delivery id was admitted before - a
    provider's retry - and `run_id` then names that first run, not a new one.
    """

    run_id: UUID
    duplicate: bool
