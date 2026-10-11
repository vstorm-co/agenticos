"""Workflow exposure schemas - a workflow's webhooks, schedules and forms (#1792)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, computed_field

from app.core.config import settings
from app.db.models.workflow_exposure import ExposureAdapter, ExposureScheduleKind
from app.schemas.base import BaseSchema, TimestampSchema
from app.workflows.contracts.fields import InputField


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
    form_token: str | None = Field(
        default=None, description="A form's link, the page's only credential; null otherwise"
    )
    channel_bot_id: UUID | None = Field(
        default=None, description="The bot whose messages a channel trigger takes; null otherwise"
    )

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

    @computed_field  # type: ignore[prop-decorator]  - pydantic reads the property
    @property
    def form_url(self) -> str | None:
        """Where a form's page is, on the console's own address. Null for any other."""
        if self.form_token is None:
            return None
        return f"{settings.FRONTEND_URL.rstrip('/')}/f/{self.form_token}"


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


class WebhookAnswer(BaseSchema):
    """What a graph's Respond to webhook step answered the delivery with.

    Not a response model: the door sends `status_code`, `headers` and `body` as
    the HTTP response itself.
    """

    status_code: int
    headers: dict[str, str]
    body: Any


class WebhookTestListening(BaseSchema):
    """A webhook's test URL, open for one call until `expires_at`.

    `test_token` is the URL's only credential, so it is returned to the editor
    who asked and never listed again.
    """

    test_token: str
    expires_at: datetime

    @computed_field  # type: ignore[prop-decorator]  - pydantic reads the property
    @property
    def url(self) -> str:
        """Where to send the test call, on the deployment's public address."""
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        return f"{base}/api/v1/workflow-webhook-tests/{self.test_token}"


class WebhookTestCaptured(BaseSchema):
    """What a test call is answered with: that it was kept. No run starts."""

    captured: bool


class WebhookTestDelivery(BaseSchema):
    """The call a test URL caught, shaped as the Webhook trigger hands one on."""

    body: dict[str, Any]
    delivery_id: str


class WebhookTestCapture(BaseSchema):
    """Where a test URL stands: waiting, holding its call, or closed without one."""

    state: Literal["listening", "caught", "expired"]
    delivery: WebhookTestDelivery | None


class WorkflowFormPage(BaseSchema):
    """What a workflow's public form shows: its words and the fields it asks for."""

    title: str
    description: str | None
    submit_label: str
    fields: list[InputField]


class WorkflowFormSubmission(BaseSchema):
    """One person's answers, by field name.

    `website` is a field the page draws out of sight: a person leaves it empty,
    and a submission that fills it in is a script's.
    """

    values: dict[str, Any] = Field(default_factory=dict)
    website: str | None = Field(default=None, max_length=200)


class WorkflowFormSubmitted(BaseSchema):
    """What the page says once the answers are in. No run is named to a stranger."""

    message: str
