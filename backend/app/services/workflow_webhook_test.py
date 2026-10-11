"""`WorkflowWebhookTestService` - a webhook's test URL, for the draft (#1949).

A webhook's own address exists only once a version is published, and every
delivery to it starts a run. The test URL is for building the graph before that:
**Listen for test event** in the editor mints one, the next call to it is kept,
and the editor shows it as the trigger's output - pinned, so the steps after it
can be tested against a real delivery. Nothing here ever starts a run.

The URL is its own credential: an unguessable token, open for
`LISTEN_SECONDS` and for one call, with no signature to check because a draft
has no signing secret yet. What it keeps lives in Redis - short-lived, and never
an at-rest record - for `KEEP_SECONDS`, and only the workflow's editors read it.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.exceptions import AppException, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import Workflow, WorkflowStatus
from app.repositories import workflow as workflow_repo
from app.schemas.workflow_exposure import (
    WebhookTestCapture,
    WebhookTestCaptured,
    WebhookTestDelivery,
    WebhookTestListening,
)
from app.services import trigger_events
from app.services.access import WORKFLOW, resolve_access
from app.services.workflow_execution.exceptions import WorkflowArchivedError
from app.services.workflow_exposure import parse_webhook_body
from app.workflows.graph.model import WorkflowGraph, pinned_output_fits
from app.workflows.nodes._triggers import WebhookTriggerOutput
from app.workflows.triggers import WEBHOOK

LISTEN_SECONDS = 120
"""How long a test URL waits for its one call."""

KEEP_SECONDS = 600
"""How long the call it caught is kept for the editor to read."""

_OPEN = "workflow:webhook-test:{token}:open"
_OWNER = "workflow:webhook-test:{token}:owner"
_CAUGHT = "workflow:webhook-test:{token}:caught"


class WebhookTestTooLargeError(AppException):
    """The test call is bigger than a step's pinned data may be (413)."""

    message = "A test call's body may take at most 64 KB, the size of a step's pinned data"
    code = "WEBHOOK_TEST_TOO_LARGE"
    status_code = 413


class WorkflowWebhookTestService:
    """Open a webhook's test URL, catch the one call to it, and hand it to the editor."""

    def __init__(self, db: AsyncSession, redis: RedisClient) -> None:
        self.db = db
        self.redis = redis

    async def listen(self, ctx: AuthContext, workflow_id: UUID) -> WebhookTestListening:
        """A fresh test URL for the workflow's draft, open for one call.

        Raises:
            NotFoundError: The workflow does not exist, or this caller may not edit it.
            WorkflowArchivedError: The workflow is archived.
            BadRequestError: The draft does not start from a webhook.
        """
        workflow = await self._editable(ctx, workflow_id)
        draft = WorkflowGraph.model_validate(workflow.draft_graph)
        if draft.node_by_id[draft.entry_node_id].definition_id != WEBHOOK:
            raise BadRequestError(
                message="Only a workflow that starts from a webhook has a test URL",
                details={"workflow_id": str(workflow_id)},
            )
        token = secrets.token_urlsafe(32)
        owner = json.dumps(
            {"organization_id": str(ctx.organization_id), "workflow_id": str(workflow.id)}
        )
        await self.redis.set(_OWNER.format(token=token), owner, ttl=KEEP_SECONDS)
        await self.redis.set(_OPEN.format(token=token), "1", ttl=LISTEN_SECONDS)
        return WebhookTestListening(
            test_token=token, expires_at=datetime.now(UTC) + timedelta(seconds=LISTEN_SECONDS)
        )

    async def catch(
        self, token: str, *, body: bytes, headers: Mapping[str, str]
    ) -> WebhookTestCaptured:
        """Keep one call to a test URL that is still open, and close it.

        Called with no auth context: the token in the path is the credential.
        The call is kept as the trigger hands a delivery on - its JSON body and
        the delivery id it named, or a made-up one when it named none.

        Raises:
            NotFoundError: No test URL is open at this token.
            BadRequestError: A body that is not a JSON object.
            WebhookTestTooLargeError: A body too big to pin.
        """
        if not await self.redis.exists(_OPEN.format(token=token)):
            raise NotFoundError(message="No test webhook is listening here")
        delivery_id = next(
            (
                found
                for source in ("webhook", "github")
                if (found := trigger_events.delivery_id(source, headers)) is not None
            ),
            f"test-{secrets.token_hex(6)}",
        )
        caught = WebhookTriggerOutput(body=parse_webhook_body(body), delivery_id=delivery_id[:255])
        output = caught.model_dump(mode="json")
        try:
            pinned_output_fits(output)
        except ValueError as exc:
            raise WebhookTestTooLargeError() from exc
        if await self.redis.getdel(_OPEN.format(token=token)) is None:
            raise NotFoundError(message="No test webhook is listening here")
        await self.redis.set(_CAUGHT.format(token=token), json.dumps(output), ttl=KEEP_SECONDS)
        return WebhookTestCaptured(captured=True)

    async def caught(self, ctx: AuthContext, workflow_id: UUID, token: str) -> WebhookTestCapture:
        """Whether a test URL still waits, caught its call, or closed with none.

        Raises:
            NotFoundError: The workflow is not reachable, or the token is not one
                of its test URLs (or is too old to remember).
        """
        workflow = await self._editable(ctx, workflow_id)
        owner = await self.redis.get(_OWNER.format(token=token))
        expected = {"organization_id": str(ctx.organization_id), "workflow_id": str(workflow.id)}
        if owner is None or json.loads(owner) != expected:
            raise NotFoundError(
                message="Test webhook not found", details={"workflow_id": workflow_id}
            )
        kept = await self.redis.get(_CAUGHT.format(token=token))
        if kept is not None:
            return WebhookTestCapture(
                state="caught", delivery=WebhookTestDelivery.model_validate_json(kept)
            )
        listening = await self.redis.exists(_OPEN.format(token=token))
        return WebhookTestCapture(state="listening" if listening else "expired", delivery=None)

    async def _editable(self, ctx: AuthContext, workflow_id: UUID) -> Workflow:
        workflow = await workflow_repo.get(
            self.db, workflow_id, organization_id=ctx.organization_id
        )
        if workflow is None or not await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        ):
            raise NotFoundError(message="Workflow not found", details={"workflow_id": workflow_id})
        if workflow.status == WorkflowStatus.ARCHIVED.value:
            raise WorkflowArchivedError(
                workflow_id=workflow.id, message="This workflow is archived"
            )
        return workflow
