"""Workflow exposure schemas - a workflow's webhooks and schedules (#1792)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import computed_field

from app.core.config import settings
from app.db.models.workflow_exposure import ExposureAdapter, ExposureScheduleKind
from app.schemas.base import BaseSchema, TimestampSchema


class WorkflowExposureUpdate(BaseSchema):
    """Pause or resume the workflow's webhook or schedule.

    Everything else about it is its trigger node's configuration, which a
    publish switches on - pausing is the one change made beside the graph, and
    it does not change whom the exposure runs as.
    """

    is_active: bool


class WorkflowExposureRead(BaseSchema, TimestampSchema):
    id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    version_number: int
    node_instance_id: UUID
    adapter: ExposureAdapter
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


class WorkflowExposureWithSecret(WorkflowExposureRead):
    """The rotate response: a webhook's new signing secret, this once.

    `WorkflowExposureRead` - every other read - has no such field, so a secret
    sealed in the vault is never exposed again.
    """

    reveal_secret: str


class WebhookAdmitted(BaseSchema):
    """What a webhook delivery is answered with: the run it admitted.

    `duplicate` is true when this delivery id was admitted before - a
    provider's retry - and `run_id` then names that first run, not a new one.
    """

    run_id: UUID
    duplicate: bool
