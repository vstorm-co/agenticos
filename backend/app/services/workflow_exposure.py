"""`WorkflowExposureService` - a workflow's webhook, GitHub hook, schedule, form, bot or mailbox.

A workflow that starts from a webhook, a GitHub, a schedule, a form, a channel
message or a Gmail trigger node gets its
exposure when a version is published (`app.services.workflow_triggers`), and
runs as the member who published it. That authority is read afresh on every
fire - a member who has since lost the workflow, or left, stops the webhook
answering, the schedule firing, the form taking answers and the bot's messages
starting it. Pausing, resuming,
rotating a webhook's secret and replacing a form's link need `workflows:edit`
and `workflows:run` on the workflow.

Firing ends in the one admission path every surface shares
(`WorkflowExecutionService.admit_pinned`), on the version the exposure pinned.
"""

import json
import logging
import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)
from app.core.permissions import AuthContext, Perm
from app.core.vault import VaultScope, seal, unseal
from app.db.models.channel_bot import ChannelBot
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_exposure import (
    ExposureAdapter,
    ExposureScheduleKind,
    WorkflowExposure,
)
from app.db.models.workflow_run import WorkflowRunStatus, WorkflowRunTrigger
from app.repositories import mcp_connection as mcp_connection_repo
from app.repositories import member_repo
from app.repositories import user as user_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_exposure as workflow_exposure_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_exposure import (
    WebhookAdmitted,
    WebhookAnswer,
    WebhookSkipped,
    WorkflowExposureRead,
    WorkflowExposureUpdate,
    WorkflowExposureWithSecret,
    WorkflowFormPage,
    WorkflowFormSubmission,
    WorkflowFormSubmitted,
    delivery_url,
)
from app.services import portal_catalog, portals, rate_limit, trigger_events
from app.services.access import WORKFLOW, resolve_access
from app.services.agent_trigger import _next_fire
from app.services.channels.base import IncomingMessage, split_thread
from app.services.mcp_connection import McpConnectionService
from app.services.workflow_authority import require_human_publisher
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowArchivedError,
    WorkflowBudgetReachedError,
    WorkflowRunInputInvalidError,
    WorkflowRunInputTooLargeError,
    WorkflowWebhookUnansweredError,
)
from app.services.workflow_execution.facade import WorkflowExecutionService
from app.workflows.graph.model import WorkflowGraph
from app.workflows.nodes._triggers import (
    ChannelMessageTriggerOutput,
    ChannelSender,
    EmailTriggerOutput,
    GithubTriggerOutput,
    ScheduleTriggerConfig,
)
from app.workflows.nodes.core_input._handler import input_problems
from app.workflows.nodes.trigger_channel_message._handler import ChannelMessageTriggerConfig
from app.workflows.nodes.trigger_form._handler import FormTriggerConfig
from app.workflows.nodes.trigger_github._handler import GithubTriggerConfig
from app.workflows.nodes.trigger_gmail._handler import GmailTriggerConfig
from app.workflows.triggers import answers_webhook

logger = logging.getLogger(__name__)

# The signed-delivery schemes a workflow webhook accepts: a relay signing with
# the generic headers, or GitHub's own. Both are HMAC-SHA256 over the raw body.
_SIGNED_SOURCES = ("webhook", "github")

# The portal whose connected account registers a GitHub trigger's hook.
_GITHUB_PORTAL = "github"

# The portal whose connected mailbox a Gmail trigger listens to, and the event
# source its messages are matched as.
_GMAIL_PORTAL = "google"
_GMAIL_SOURCE = "gmail"

# The run states a schedule waits behind rather than fire on top of.
_TERMINAL = {"succeeded", "failed", "cancelled", "budget_exceeded"}

# How often a delivery waiting on its graph's answer looks for it.
_ANSWER_POLL_SECONDS = 0.2


def _read(exposure: WorkflowExposure, version: int) -> WorkflowExposureRead:
    return WorkflowExposureRead(
        id=exposure.id,
        workflow_id=exposure.workflow_id,
        workflow_version_id=exposure.workflow_version_id,
        version_number=version,
        adapter=ExposureAdapter(exposure.adapter),
        node_instance_id=exposure.node_instance_id,
        is_active=exposure.is_active,
        execution_principal_user_id=exposure.execution_principal_user_id,
        run_input=exposure.run_input,
        schedule_kind=(
            ExposureScheduleKind(exposure.schedule_kind) if exposure.schedule_kind else None
        ),
        interval_seconds=exposure.interval_seconds,
        cron_expression=exposure.cron_expression,
        next_fire_at=exposure.next_fire_at,
        last_fired_at=exposure.last_fired_at,
        last_run_id=exposure.last_run_id,
        form_token=exposure.form_token,
        channel_bot_id=exposure.channel_bot_id,
        provider_target=exposure.provider_target,
        registered_on_provider=exposure.provider_webhook_id is not None,
        created_at=exposure.created_at,
        updated_at=exposure.updated_at,
    )


def parse_webhook_body(body: bytes) -> dict[str, Any]:
    """A delivery's body as the JSON object its run starts with, or a 400."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BadRequestError(message="Webhook body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise BadRequestError(message="Webhook body must be a JSON object")
    return payload


def workflow_timezone(workflow: Workflow) -> str:
    """The timezone a workflow's schedule keeps: its setting, UTC when it has none."""
    timezone = workflow.settings.get("timezone")
    return timezone if isinstance(timezone, str) else "UTC"


def _next_tick(exposure: WorkflowExposure, *, now: datetime) -> datetime:
    """When a schedule exposure next fires after `now`, in its own timezone."""
    return _next_fire(
        schedule_kind=cast(str, exposure.schedule_kind),
        interval_seconds=exposure.interval_seconds,
        cron_expression=exposure.cron_expression,
        now=now,
        timezone=exposure.timezone,
    )


class WorkflowExposureService:
    """Create, change, remove and fire a workflow's webhooks and schedules."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runs = WorkflowExecutionService(db)

    async def get_for_workflow(
        self, ctx: AuthContext, workflow_id: UUID
    ) -> WorkflowExposureRead | None:
        """The workflow's webhook or schedule, if its live version starts from one.

        Raises:
            NotFoundError: The workflow does not exist, or this caller may not view it.
        """
        workflow = await self._workflow(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        exposure = await workflow_exposure_repo.get_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        if exposure is None:
            return None
        return _read(exposure, await self._version_number(exposure))

    async def switch_on_webhook(
        self, ctx: AuthContext, workflow: Workflow, version: WorkflowVersion, node_id: UUID
    ) -> tuple[WorkflowExposureRead, str | None]:
        """The webhook of a version just published, run as its publisher.

        The row the same node had is kept - its address and signing secret with
        it - and takes the new version over; a first publish of the node makes
        one, and mints the secret returned here this once.
        """
        exposure = await self._reusable(ctx, workflow, node_id, ExposureAdapter.WEBHOOK)
        live = {
            "workflow_version_id": version.id,
            "execution_principal_user_id": ctx.subject_id,
            "is_active": True,
        }
        if exposure is not None:
            exposure = await workflow_exposure_repo.update(
                self.db, exposure=exposure, update_data=live
            )
            await self._audit(ctx, exposure, "workflow.exposure_updated")
            return _read(exposure, version.version), None
        secret = secrets.token_urlsafe(32)
        sealed = seal(secret, scope=VaultScope.organization(ctx.organization_id))
        exposure = await workflow_exposure_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            node_instance_id=node_id,
            adapter=ExposureAdapter.WEBHOOK.value,
            run_input={},
            secret_encrypted=sealed.ciphertext,
            secret_key_version=sealed.key_version,
            **live,
        )
        await self._audit(ctx, exposure, "workflow.exposure_created")
        return _read(exposure, version.version), secret

    async def switch_on_form(
        self, ctx: AuthContext, workflow: Workflow, version: WorkflowVersion, node_id: UUID
    ) -> WorkflowExposureRead:
        """The form of a version just published, run as its publisher.

        The row the same node had is kept - its link with it - and takes the new
        version over; a first publish of the node mints the link.
        """
        exposure = await self._reusable(ctx, workflow, node_id, ExposureAdapter.FORM)
        live = {
            "workflow_version_id": version.id,
            "execution_principal_user_id": ctx.subject_id,
            "is_active": True,
        }
        if exposure is not None:
            exposure = await workflow_exposure_repo.update(
                self.db, exposure=exposure, update_data=live
            )
            await self._audit(ctx, exposure, "workflow.exposure_updated")
            return _read(exposure, version.version)
        exposure = await workflow_exposure_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            node_instance_id=node_id,
            adapter=ExposureAdapter.FORM.value,
            run_input={},
            form_token=secrets.token_urlsafe(24),
            **live,
        )
        await self._audit(ctx, exposure, "workflow.exposure_created")
        return _read(exposure, version.version)

    async def switch_on_channel(
        self,
        ctx: AuthContext,
        workflow: Workflow,
        version: WorkflowVersion,
        node_id: UUID,
        config: ChannelMessageTriggerConfig,
    ) -> WorkflowExposureRead:
        """The bot a version just published listens to, run as its publisher.

        Raises:
            AlreadyExistsError: Another workflow's messages trigger already takes
                this bot's messages. A bot starts one workflow at most, so which one
                a message starts never depends on the order they were published in.
        """
        taken = await workflow_exposure_repo.get_channel_listener(self.db, config.bot_id)
        if taken is not None and taken.workflow_id != workflow.id:
            raise AlreadyExistsError(
                message="Another workflow already starts from this bot's messages",
                details={"bot_id": str(config.bot_id), "workflow_id": str(taken.workflow_id)},
            )
        exposure = await self._reusable(ctx, workflow, node_id, ExposureAdapter.CHANNEL)
        live = {
            "workflow_version_id": version.id,
            "execution_principal_user_id": ctx.subject_id,
            "is_active": True,
            "channel_bot_id": config.bot_id,
        }
        if exposure is not None:
            exposure = await workflow_exposure_repo.update(
                self.db, exposure=exposure, update_data=live
            )
            await self._audit(ctx, exposure, "workflow.exposure_updated")
            return _read(exposure, version.version)
        exposure = await workflow_exposure_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            node_instance_id=node_id,
            adapter=ExposureAdapter.CHANNEL.value,
            run_input={},
            **live,
        )
        await self._audit(ctx, exposure, "workflow.exposure_created")
        return _read(exposure, version.version)

    async def switch_on_github(
        self,
        ctx: AuthContext,
        workflow: Workflow,
        version: WorkflowVersion,
        node_id: UUID,
        config: GithubTriggerConfig,
    ) -> tuple[WorkflowExposureRead, str | None]:
        """The GitHub hook of a version just published, run as its publisher.

        The row the same node had is kept, with its address and secret. The hook is
        registered on the repository again through the organization's connected
        account on every publish, so a change of repository or events reaches
        GitHub; the secret is returned this once when it has to be pasted by hand -
        a first publish the account could not register, or one the account no
        longer registers after it did.
        """
        exposure = await self._reusable(ctx, workflow, node_id, ExposureAdapter.GITHUB)
        live = {
            "workflow_version_id": version.id,
            "execution_principal_user_id": ctx.subject_id,
            "is_active": True,
        }
        if exposure is None:
            secret = secrets.token_urlsafe(32)
            sealed = seal(secret, scope=VaultScope.organization(ctx.organization_id))
            exposure = await workflow_exposure_repo.create(
                self.db,
                organization_id=ctx.organization_id,
                workflow_id=workflow.id,
                node_instance_id=node_id,
                adapter=ExposureAdapter.GITHUB.value,
                run_input={},
                secret_encrypted=sealed.ciphertext,
                secret_key_version=sealed.key_version,
                **live,
            )
            await self._audit(ctx, exposure, "workflow.exposure_created")
            was_registered, is_new = False, True
        else:
            was_registered, is_new = exposure.provider_webhook_id is not None, False
            exposure = await workflow_exposure_repo.update(
                self.db, exposure=exposure, update_data=live
            )
            await self._audit(ctx, exposure, "workflow.exposure_updated")
            secret = self._secret_of(exposure)
        registered = await self._register_github(ctx, exposure, config, secret)
        reveal = secret if not registered and (is_new or was_registered) else None
        return _read(exposure, version.version), reveal

    async def switch_on_gmail(
        self, ctx: AuthContext, workflow: Workflow, version: WorkflowVersion, node_id: UUID
    ) -> WorkflowExposureRead:
        """The mailbox listener of a version just published, run as its publisher.

        Raises:
            BadRequestError: The organization has no Gmail mailbox connected, so
                nothing would ever start the workflow.
        """
        grant = await mcp_connection_repo.get_portal_grant(
            self.db, organization_id=ctx.organization_id, portal_key=_GMAIL_PORTAL
        )
        if grant is None:
            raise BadRequestError(
                message="Connect the organization's Gmail mailbox first - from the Gmail "
                "trigger step, or the Gmail portal",
                details={"workflow_id": str(workflow.id)},
            )
        exposure = await self._reusable(ctx, workflow, node_id, ExposureAdapter.GMAIL)
        live = {
            "workflow_version_id": version.id,
            "execution_principal_user_id": ctx.subject_id,
            "is_active": True,
        }
        if exposure is not None:
            exposure = await workflow_exposure_repo.update(
                self.db, exposure=exposure, update_data=live
            )
            await self._audit(ctx, exposure, "workflow.exposure_updated")
            return _read(exposure, version.version)
        exposure = await workflow_exposure_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            node_instance_id=node_id,
            adapter=ExposureAdapter.GMAIL.value,
            run_input={},
            **live,
        )
        await self._audit(ctx, exposure, "workflow.exposure_created")
        return _read(exposure, version.version)

    async def switch_on_schedule(
        self,
        ctx: AuthContext,
        workflow: Workflow,
        version: WorkflowVersion,
        node_id: UUID,
        config: ScheduleTriggerConfig,
    ) -> WorkflowExposureRead:
        """The schedule of a version just published, run as its publisher.

        Its clock restarts from now when it is new, its cadence changed or it
        was paused - a paused schedule does not owe the runs it missed - and
        otherwise keeps the tick it was counting to.
        """
        exposure = await self._reusable(ctx, workflow, node_id, ExposureAdapter.SCHEDULE)
        now = datetime.now(UTC)
        interval = config.interval_seconds if config.schedule_kind == "interval" else None
        cron = config.cron_expression if config.schedule_kind == "cron" else None
        timezone = workflow_timezone(workflow)
        fields: dict[str, Any] = {
            "timezone": timezone,
            "workflow_version_id": version.id,
            "execution_principal_user_id": ctx.subject_id,
            "is_active": True,
            "run_input": config.input,
            "schedule_kind": config.schedule_kind,
            "interval_seconds": interval,
            "cron_expression": cron,
        }
        if (
            exposure is None
            or not exposure.is_active
            or (
                exposure.schedule_kind,
                exposure.interval_seconds,
                exposure.cron_expression,
                exposure.timezone,
            )
            != (config.schedule_kind, interval, cron, timezone)
        ):
            fields["next_fire_at"] = _next_fire(
                schedule_kind=config.schedule_kind,
                interval_seconds=interval,
                cron_expression=cron,
                now=now,
                timezone=timezone,
            )
        if exposure is not None:
            exposure = await workflow_exposure_repo.update(
                self.db, exposure=exposure, update_data=fields
            )
            await self._audit(ctx, exposure, "workflow.exposure_updated")
            return _read(exposure, version.version)
        exposure = await workflow_exposure_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            node_instance_id=node_id,
            adapter=ExposureAdapter.SCHEDULE.value,
            **fields,
        )
        await self._audit(ctx, exposure, "workflow.exposure_created")
        return _read(exposure, version.version)

    async def switch_off(self, ctx: AuthContext, workflow: Workflow) -> None:
        """Remove the workflow's exposure: its live version starts some other way.

        Runs it already admitted keep going.
        """
        exposure = await workflow_exposure_repo.get_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        if exposure is not None:
            await self._remove(ctx, exposure)

    async def set_active(
        self, ctx: AuthContext, workflow_id: UUID, exposure_id: UUID, data: WorkflowExposureUpdate
    ) -> WorkflowExposureRead:
        """Pause or resume the exposure. A schedule resumed counts from now.

        Raises:
            NotFoundError: The workflow or the exposure is not reachable.
            AuthorizationError: The caller may edit the workflow but not run it.
            WorkflowArchivedError: The workflow is archived.
        """
        workflow = await self._editable(ctx, workflow_id)
        exposure = await self._exposure(ctx, workflow, exposure_id)
        if data.is_active:
            require_human_publisher(ctx)
        changes: dict[str, Any] = {"is_active": data.is_active}
        if (
            data.is_active
            and not exposure.is_active
            and exposure.adapter == ExposureAdapter.SCHEDULE.value
        ):
            changes["next_fire_at"] = _next_tick(exposure, now=datetime.now(UTC))
        exposure = await workflow_exposure_repo.update(
            self.db, exposure=exposure, update_data=changes
        )
        await self._audit(
            ctx,
            exposure,
            "workflow.exposure_resumed" if data.is_active else "workflow.exposure_paused",
        )
        return _read(exposure, await self._version_number(exposure))

    async def retime(self, ctx: AuthContext, workflow: Workflow) -> None:
        """Keep the workflow's schedule in its timezone, just changed: a cron schedule
        that is on counts to its next tick there from now. An interval keeps its count."""
        exposure = await workflow_exposure_repo.get_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        timezone = workflow_timezone(workflow)
        if (
            exposure is None
            or exposure.adapter != ExposureAdapter.SCHEDULE.value
            or exposure.timezone == timezone
        ):
            return
        require_human_publisher(ctx)
        changes: dict[str, Any] = {"timezone": timezone}
        if exposure.is_active and exposure.schedule_kind == "cron":
            changes["next_fire_at"] = _next_fire(
                schedule_kind=cast(str, exposure.schedule_kind),
                interval_seconds=exposure.interval_seconds,
                cron_expression=exposure.cron_expression,
                now=datetime.now(UTC),
                timezone=timezone,
            )
        await workflow_exposure_repo.update(self.db, exposure=exposure, update_data=changes)

    async def pause(self, ctx: AuthContext, workflow: Workflow) -> None:
        """Pause the workflow's webhook or schedule, if it has one that is on.

        What archiving a workflow does, and so needs no more than editing it: a
        pause starts nothing, and nothing runs as anyone because of it.
        """
        exposure = await workflow_exposure_repo.get_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        if exposure is None or not exposure.is_active:
            return
        await workflow_exposure_repo.update(
            self.db, exposure=exposure, update_data={"is_active": False}
        )
        await self._audit(ctx, exposure, "workflow.exposure_paused")

    async def rotate_secret(
        self, ctx: AuthContext, workflow_id: UUID, exposure_id: UUID
    ) -> WorkflowExposureWithSecret:
        """A new signing secret for a webhook, returned once; the old one stops verifying.

        Raises:
            NotFoundError: The workflow or the exposure is not reachable.
            AuthorizationError: The caller may edit the workflow but not run it.
            WorkflowArchivedError: The workflow is archived.
            BadRequestError: The exposure is a schedule, which has no secret.
        """
        workflow = await self._editable(ctx, workflow_id)
        exposure = await self._exposure(ctx, workflow, exposure_id)
        require_human_publisher(ctx)
        if exposure.adapter not in (ExposureAdapter.WEBHOOK.value, ExposureAdapter.GITHUB.value):
            raise BadRequestError(
                message="Only a webhook or a GitHub trigger has a signing secret",
                details={"exposure_id": str(exposure.id)},
            )
        secret = secrets.token_urlsafe(32)
        sealed = seal(secret, scope=VaultScope.organization(exposure.organization_id))
        exposure = await workflow_exposure_repo.update(
            self.db,
            exposure=exposure,
            update_data={
                "secret_encrypted": sealed.ciphertext,
                "secret_key_version": sealed.key_version,
            },
        )
        await self._audit(ctx, exposure, "workflow.exposure_secret_rotated")
        if exposure.provider_webhook_id is not None:
            # The hook GitHub holds signs with the old secret: register it again.
            await self._register_github(ctx, exposure, await self._github_config(exposure), secret)
        return WorkflowExposureWithSecret(
            **_read(exposure, await self._version_number(exposure)).model_dump(),
            reveal_secret=secret,
        )

    async def renew_form_link(
        self, ctx: AuthContext, workflow_id: UUID, exposure_id: UUID
    ) -> WorkflowExposureRead:
        """A new link for a form; the old one then answers as if there were no form.

        Raises:
            NotFoundError: The workflow or the exposure is not reachable.
            AuthorizationError: The caller may edit the workflow but not run it.
            WorkflowArchivedError: The workflow is archived.
            BadRequestError: The exposure is not a form.
        """
        workflow = await self._editable(ctx, workflow_id)
        exposure = await self._exposure(ctx, workflow, exposure_id)
        require_human_publisher(ctx)
        if exposure.adapter != ExposureAdapter.FORM.value:
            raise BadRequestError(
                message="Only a form has a link to replace",
                details={"exposure_id": str(exposure.id)},
            )
        exposure = await workflow_exposure_repo.update(
            self.db, exposure=exposure, update_data={"form_token": secrets.token_urlsafe(24)}
        )
        await self._audit(ctx, exposure, "workflow.exposure_link_renewed")
        return _read(exposure, await self._version_number(exposure))

    async def form_page(self, token: str) -> WorkflowFormPage:
        """What the form behind `token` shows a visitor.

        Raises:
            NotFoundError: No open form has this link - replaced, paused, or its
                publisher can no longer run the workflow. One answer for all of
                them, so a link reveals nothing about why it stopped working.
        """
        _exposure, config, _fire = await self._open_form(token)
        return WorkflowFormPage(
            title=config.title,
            description=config.description,
            submit_label=config.submit_label,
            fields=list(config.fields),
        )

    async def submit_form(
        self, token: str, submission: WorkflowFormSubmission
    ) -> WorkflowFormSubmitted:
        """Start one run with a visitor's answers, as the form's publisher.

        A submission that fills in the hidden trap field is thanked and starts
        nothing: answering it any other way would teach a script what to skip.

        Raises:
            NotFoundError: As `form_page`.
            WorkflowRunInputInvalidError: The answers do not fit the form's fields.
            WorkflowRunInputTooLargeError: The answers are over the size limit.
            WorkflowAdmissionQuotaError: Too much of the organization's work is
                already in flight.
        """
        exposure, config, (ctx, workflow, version) = await self._open_form(token)
        thanks = WorkflowFormSubmitted(message=config.success_message)
        if submission.website:
            logger.info("workflow_form_trap_filled", extra={"exposure_id": str(exposure.id)})
            return thanks
        problems = input_problems(config, submission.values)
        if problems:
            raise WorkflowRunInputInvalidError(problems=problems)
        run, _entry = await self.runs.admit_pinned(
            ctx,
            workflow,
            version,
            triggered_by=WorkflowRunTrigger.FORM,
            run_input=submission.values,
        )
        await workflow_exposure_repo.update(
            self.db,
            exposure=exposure,
            update_data={"last_fired_at": datetime.now(UTC), "last_run_id": run.id},
        )
        return thanks

    async def _open_form(
        self, token: str
    ) -> tuple[WorkflowExposure, FormTriggerConfig, tuple[AuthContext, Workflow, WorkflowVersion]]:
        """The form behind `token`, its configuration and the context it runs in."""
        exposure = await workflow_exposure_repo.get_by_form_token(self.db, token)
        fire = None
        if exposure is not None and exposure.is_active:
            fire = await self._fire_context(exposure)
        if exposure is None or fire is None:
            raise NotFoundError(message="Form not found")
        version = fire[2]
        node = WorkflowGraph.model_validate(version.graph).node_by_id[exposure.node_instance_id]
        return exposure, FormTriggerConfig.model_validate(node.config), fire

    async def receive_channel_message(
        self, bot: ChannelBot, incoming: IncomingMessage, *, sender_user_id: UUID | None
    ) -> bool:
        """Start the run a message to `bot` starts, and say whether one took it.

        `incoming` has passed the bot's own admission - its access policy, the
        sender's link, the mention rule - so this decides only whether the
        workflow listening to the bot takes it: one is live and on, its publisher
        can still run it, and the message fits its filter. `False` leaves the
        message to the bot's agent.

        Raises:
            WorkflowAdmissionQuotaError: Too much of the organization's work is in
                flight to admit the run.
            WorkflowRunInputTooLargeError: The message is over the input limit.
        """
        exposure = await workflow_exposure_repo.get_channel_listener(self.db, bot.id)
        if exposure is None or not exposure.is_active:
            return False
        fire = await self._fire_context(exposure)
        if fire is None:
            logger.warning(
                "workflow_channel_trigger_cannot_run", extra={"exposure_id": str(exposure.id)}
            )
            return False
        ctx, workflow, version = fire
        node = WorkflowGraph.model_validate(version.graph).node_by_id[exposure.node_instance_id]
        config = ChannelMessageTriggerConfig.model_validate(node.config)
        if not config.takes(chat_type=incoming.chat_type, text=incoming.text):
            return False
        channel_id, thread_id = split_thread(incoming.platform_chat_id)
        message = ChannelMessageTriggerOutput(
            platform=incoming.platform,
            bot_id=bot.id,
            channel_id=channel_id,
            thread_id=thread_id,
            chat_type="private" if incoming.chat_type == "private" else "group",
            message_id=incoming.message_id,
            text=incoming.text,
            sender=ChannelSender(
                platform_user_id=incoming.platform_user_id,
                username=incoming.platform_username,
                display_name=incoming.platform_display_name,
                user_id=sender_user_id,
            ),
        )
        run, _entry = await self.runs.admit_pinned(
            ctx,
            workflow,
            version,
            triggered_by=WorkflowRunTrigger.CHANNEL_MESSAGE,
            run_input=message.model_dump(mode="json"),
        )
        await workflow_exposure_repo.update(
            self.db,
            exposure=exposure,
            update_data={"last_fired_at": datetime.now(UTC), "last_run_id": run.id},
        )
        return True

    async def receive_polled_email(
        self, *, organization_id: UUID, events: Sequence[portals.PolledEvent]
    ) -> bool:
        """Start the runs one poll of the organization's mailbox starts, and say
        whether every one that should start was admitted.

        Called by the portal poll, in its transaction, beside the agent triggers'
        fires: each new message is matched against every live Gmail trigger, and
        each match starts one run - recorded against the message's id, so a message
        a later poll reads again starts nothing twice. `False` when the
        organization had too much work in flight to admit one: the poll then keeps
        its place, and reads the same messages again a minute later.
        """
        exposures = await workflow_exposure_repo.list_active(
            self.db, organization_id=organization_id, adapter=ExposureAdapter.GMAIL.value
        )
        admitted_all = True
        for exposure in exposures:
            fire = await self._fire_context(exposure)
            if fire is None:
                logger.warning(
                    "workflow_gmail_trigger_cannot_run", extra={"exposure_id": str(exposure.id)}
                )
                continue
            ctx, workflow, version = fire
            node = WorkflowGraph.model_validate(version.graph).node_by_id[exposure.node_instance_id]
            config = GmailTriggerConfig.model_validate(node.config)
            for event in events:
                if not trigger_events.event_matches(
                    _GMAIL_SOURCE,
                    headers={},
                    payload=event.payload,
                    config=config.model_dump(exclude_none=True),
                ):
                    continue
                if not await self._admit_email(ctx, workflow, version, exposure, event):
                    admitted_all = False
        return admitted_all

    async def _admit_email(
        self,
        ctx: AuthContext,
        workflow: Workflow,
        version: WorkflowVersion,
        exposure: WorkflowExposure,
        event: portals.PolledEvent,
    ) -> bool:
        """Admit one message's run, unless it already has one; `False` when refused."""
        await workflow_exposure_repo.lock_delivery(
            self.db, exposure_id=exposure.id, delivery_id=event.delivery_id
        )
        if await workflow_exposure_repo.get_delivery(
            self.db, exposure_id=exposure.id, delivery_id=event.delivery_id
        ):
            return True
        payload = event.payload
        message = EmailTriggerOutput(
            message_id=str(payload.get("message_id") or event.delivery_id),
            sender=str(payload.get("from") or ""),
            to=str(payload.get("to") or ""),
            subject=str(payload.get("subject") or ""),
            text=str(payload.get("text") or ""),
            snippet=str(payload.get("snippet") or ""),
            labels=[str(one) for one in payload.get("labels") or []],
        )
        try:
            run, _entry = await self.runs.admit_pinned(
                ctx,
                workflow,
                version,
                triggered_by=WorkflowRunTrigger.GMAIL,
                run_input=message.model_dump(mode="json"),
            )
        except WorkflowAdmissionQuotaError:
            return False
        except (WorkflowBudgetReachedError, WorkflowRunInputTooLargeError) as exc:
            # Not a refusal a later poll would lift: the month's budget is spent, or
            # the message stays too large. It is skipped rather than read for ever.
            logger.warning(
                "workflow_gmail_message_refused",
                extra={"exposure_id": str(exposure.id), "reason": type(exc).__name__},
            )
            return True
        await workflow_exposure_repo.create_delivery(
            self.db,
            organization_id=exposure.organization_id,
            exposure_id=exposure.id,
            delivery_id=event.delivery_id,
            workflow_run_id=run.id,
        )
        await workflow_exposure_repo.update(
            self.db,
            exposure=exposure,
            update_data={"last_fired_at": datetime.now(UTC), "last_run_id": run.id},
        )
        return True

    async def receive_github(
        self, exposure_id: UUID, *, body: bytes, headers: Mapping[str, str]
    ) -> WebhookAdmitted | WebhookSkipped:
        """Admit one GitHub delivery as one run, skip one the trigger does not name,
        or answer a redelivery with the run it already admitted.

        Called with no auth context: the delivery is authenticated by GitHub's
        `X-Hub-Signature-256` under the exposure's own secret, and the run acts as
        the exposure's member.

        Raises:
            NotFoundError: No active GitHub trigger has this id.
            AuthorizationError: The signature did not verify, or the member it
                runs as can no longer run the workflow.
            BadRequestError: No `X-GitHub-Delivery`, or a body that is not a JSON
                object.
            WorkflowRunInputTooLargeError: The delivery is over the input limit.
        """
        exposure = await workflow_exposure_repo.get_by_id(self.db, exposure_id)
        if (
            exposure is None
            or exposure.adapter != ExposureAdapter.GITHUB.value
            or not exposure.is_active
        ):
            raise NotFoundError(message="Webhook not found", details={"exposure_id": exposure_id})
        if not trigger_events.verify_signature(
            "github", secret=self._secret_of(exposure), body=body, headers=headers
        ):
            raise AuthorizationError(
                message="Webhook signature did not verify",
                details={"exposure_id": str(exposure_id)},
            )
        delivery_id = trigger_events.delivery_id("github", headers)
        if delivery_id is None or len(delivery_id) > 255:
            raise BadRequestError(
                message="A GitHub delivery names itself in X-GitHub-Delivery",
                details={"exposure_id": str(exposure_id)},
            )
        payload = parse_webhook_body(body)
        fire = await self._fire_context(exposure)
        if fire is None:
            raise AuthorizationError(
                message="The member this trigger runs as can no longer run this workflow",
                details={"exposure_id": str(exposure_id)},
            )
        ctx, workflow, version = fire
        config = await self._github_config(exposure)
        event = headers.get("x-github-event", "")
        action = payload.get("action")
        repository = payload.get("repository")
        full_name = repository.get("full_name") if isinstance(repository, dict) else None
        sender = payload.get("sender")
        login = sender.get("login") if isinstance(sender, dict) else None
        named_action = action if isinstance(action, str) else None
        if not isinstance(full_name, str) or not config.takes(
            event=event, action=named_action, repository=full_name
        ):
            what = event or "an unnamed event"
            if named_action is not None:
                what = f"{what} {named_action}"
            where = f" on {full_name}" if isinstance(full_name, str) else ""
            return WebhookSkipped(skipped=f"{what}{where} is not one this trigger starts on")

        await workflow_exposure_repo.lock_delivery(
            self.db, exposure_id=exposure.id, delivery_id=delivery_id
        )
        seen = await workflow_exposure_repo.get_delivery(
            self.db, exposure_id=exposure.id, delivery_id=delivery_id
        )
        if seen is not None:
            return WebhookAdmitted(run_id=seen.workflow_run_id, duplicate=True)
        await self._spend_delivery_allowance(exposure)
        delivery = GithubTriggerOutput(
            event=event,
            action=named_action,
            repository=full_name,
            sender=login if isinstance(login, str) else None,
            delivery_id=delivery_id,
            payload=payload,
        )
        run, _entry = await self.runs.admit_pinned(
            ctx,
            workflow,
            version,
            triggered_by=WorkflowRunTrigger.GITHUB,
            run_input=delivery.model_dump(mode="json"),
        )
        await workflow_exposure_repo.create_delivery(
            self.db,
            organization_id=exposure.organization_id,
            exposure_id=exposure.id,
            delivery_id=delivery_id,
            workflow_run_id=run.id,
        )
        await workflow_exposure_repo.update(
            self.db,
            exposure=exposure,
            update_data={"last_fired_at": datetime.now(UTC), "last_run_id": run.id},
        )
        return WebhookAdmitted(run_id=run.id, duplicate=False)

    async def receive_webhook(
        self, exposure_id: UUID, *, body: bytes, headers: Mapping[str, str]
    ) -> WebhookAdmitted | WebhookAnswer:
        """Admit one signed delivery as one run, or answer with the run it already admitted.

        Called with no auth context: the delivery is authenticated by its HMAC
        against the exposure's own secret, and the run acts as the exposure's
        member. Every delivery must name itself (`X-Delivery-Id`, or GitHub's
        `X-GitHub-Delivery`); the id is recorded in the transaction that admits
        the run, so a retry of it - however late - returns the first run.

        A version whose graph holds a Respond to webhook step is answered by it:
        the admission is committed here, so the run can start, and the delivery
        waits up to `WORKFLOW_WEBHOOK_RESPONSE_TIMEOUT_SECONDS` for the answer
        (see `_answer`). A retry of a delivery that was answered gets the same
        answer.

        Raises:
            NotFoundError: No active webhook has this id.
            AuthorizationError: The signature did not verify, or the member it
                runs as can no longer run the workflow.
            BadRequestError: No delivery id, or a body that is not a JSON object.
            WorkflowWebhookUnansweredError: The graph answers its deliveries, and
                this run failed, was cancelled or ran out of budget first.
        """
        exposure = await workflow_exposure_repo.get_by_id(self.db, exposure_id)
        if (
            exposure is None
            or exposure.adapter != ExposureAdapter.WEBHOOK.value
            or not exposure.is_active
        ):
            raise NotFoundError(message="Webhook not found", details={"exposure_id": exposure_id})
        secret = self._secret_of(exposure)
        if not any(
            trigger_events.verify_signature(source, secret=secret, body=body, headers=headers)
            for source in _SIGNED_SOURCES
        ):
            raise AuthorizationError(
                message="Webhook signature did not verify",
                details={"exposure_id": str(exposure_id)},
            )
        delivery_id = next(
            (
                found
                for source in _SIGNED_SOURCES
                if (found := trigger_events.delivery_id(source, headers)) is not None
            ),
            None,
        )
        if delivery_id is None or len(delivery_id) > 255:
            raise BadRequestError(
                message="A delivery needs an X-Delivery-Id header of at most 255 characters",
                details={"exposure_id": str(exposure_id)},
            )
        payload = parse_webhook_body(body)

        await workflow_exposure_repo.lock_delivery(
            self.db, exposure_id=exposure.id, delivery_id=delivery_id
        )
        seen = await workflow_exposure_repo.get_delivery(
            self.db, exposure_id=exposure.id, delivery_id=delivery_id
        )
        if seen is not None:
            return await self._replay(seen.workflow_run_id)
        await self._spend_delivery_allowance(exposure)

        fire = await self._fire_context(exposure)
        if fire is None:
            raise AuthorizationError(
                message="The member this webhook runs as can no longer run this workflow",
                details={"exposure_id": str(exposure_id)},
            )
        ctx, workflow, version = fire
        run, _entry = await self.runs.admit_pinned(
            ctx,
            workflow,
            version,
            triggered_by=WorkflowRunTrigger.WEBHOOK,
            run_input={"body": payload, "delivery_id": delivery_id},
        )
        await workflow_exposure_repo.create_delivery(
            self.db,
            organization_id=exposure.organization_id,
            exposure_id=exposure.id,
            delivery_id=delivery_id,
            workflow_run_id=run.id,
        )
        await workflow_exposure_repo.update(
            self.db,
            exposure=exposure,
            update_data={"last_fired_at": datetime.now(UTC), "last_run_id": run.id},
        )
        if answers_webhook(WorkflowGraph.model_validate(version.graph)):
            answer = await self._answer(run.id)
            if answer is not None:
                return answer
        return WebhookAdmitted(run_id=run.id, duplicate=False)

    async def _spend_delivery_allowance(self, exposure: WorkflowExposure) -> None:
        """Count one run against the exposure's per-minute allowance.

        Called once the signature has verified and the delivery would start a run,
        so neither a stranger's request nor a delivery the trigger skips or has
        already answered spends it.

        Raises:
            RateLimitError: The exposure has started as many runs this minute as it may.
        """
        decision = await rate_limit.workflow_webhook_allowed(str(exposure.id))
        if not decision.allowed:
            raise RateLimitError(
                message="This webhook is taking too many deliveries. Try again shortly.",
                details={"retry_after_seconds": decision.retry_after_seconds},
            )

    async def _replay(self, run_id: UUID) -> WebhookAdmitted | WebhookAnswer:
        """What a retried delivery gets: the answer its first run gave, if it gave one."""
        _status, answered = await workflow_run_repo.get_run_answer(self.db, run_id)
        if answered is not None:
            return WebhookAnswer.model_validate(answered)
        return WebhookAdmitted(run_id=run_id, duplicate=True)

    async def _answer(self, run_id: UUID) -> WebhookAnswer | None:
        """Wait for a run's Respond to webhook step, and return what it answered.

        Commits the request's transaction first - the one route that does: the
        run and its delivery record must be visible to the worker before there
        is anything to wait for, and the request's own commit comes only once
        the route returns. The run's first dispatch job commits with it, and
        `NOTIFY` wakes a worker on that commit. Nothing is written after, so the
        `DBSession` commit that follows has nothing left to do.

        Returns None when the time runs out, or when the run succeeded without
        answering - the sender then gets the `202` any delivery gets.

        Raises:
            WorkflowWebhookUnansweredError: The run ended badly before answering.
        """
        await self.db.commit()
        with anyio.move_on_after(settings.WORKFLOW_WEBHOOK_RESPONSE_TIMEOUT_SECONDS):
            while True:
                status, answer = await workflow_run_repo.get_run_answer(self.db, run_id)
                if answer is not None:
                    return WebhookAnswer.model_validate(answer)
                if status == WorkflowRunStatus.SUCCEEDED.value:
                    return None
                if status in _TERMINAL:
                    raise WorkflowWebhookUnansweredError(run_id=run_id, status=status)
                await anyio.sleep(_ANSWER_POLL_SECONDS)
        return None

    async def fire_due(self, *, now: datetime, limit: int = 100) -> list[tuple[UUID, UUID]]:
        """Fire every schedule due by `now`, and return what it admitted.

        Each claimed schedule's clock advances in this transaction whatever
        happens next, so a tick is spent once: a schedule whose last run is still
        going skips it rather than stack a second run behind the first, and one
        whose run is refused (a quota, an oversized input) logs and waits for its
        next tick. A schedule whose member can no longer run it is switched off
        and audited - retrying against a wall every minute helps nobody.

        Returns `(run_id, entry_node_run_id)` for every admitted run. Each run's
        first dispatch job is queued in this transaction, with the run.
        """
        admitted: list[tuple[UUID, UUID]] = []
        for exposure in await workflow_exposure_repo.claim_due_schedules(
            self.db, now=now, limit=limit
        ):
            await workflow_exposure_repo.update(
                self.db,
                exposure=exposure,
                update_data={"next_fire_at": _next_tick(exposure, now=now)},
            )
            if await self._last_run_live(exposure):
                continue
            fire = await self._fire_context(exposure)
            if fire is None:
                await self._disable(exposure)
                continue
            ctx, workflow, version = fire
            try:
                # A savepoint, so a refused admission undoes only its own writes
                # and the clock advanced above still commits.
                async with self.db.begin_nested():
                    run, entry_node_run_id = await self.runs.admit_pinned(
                        ctx,
                        workflow,
                        version,
                        triggered_by=WorkflowRunTrigger.SCHEDULE,
                        run_input={"fired_at": now.isoformat(), "input": exposure.run_input},
                    )
            except (
                WorkflowAdmissionQuotaError,
                WorkflowBudgetReachedError,
                WorkflowRunInputTooLargeError,
            ) as exc:
                logger.warning(
                    "workflow_schedule_refused",
                    extra={"exposure_id": str(exposure.id), "reason": type(exc).__name__},
                )
                continue
            await workflow_exposure_repo.update(
                self.db,
                exposure=exposure,
                update_data={"last_fired_at": now, "last_run_id": run.id},
            )
            admitted.append((run.id, entry_node_run_id))
        return admitted

    async def _fire_context(
        self, exposure: WorkflowExposure
    ) -> tuple[AuthContext, Workflow, WorkflowVersion] | None:
        """The member an exposure runs as, its workflow and pinned version - or
        None when that member can no longer run it.

        Re-resolved on every fire, never cached: authority is whatever the
        member's membership and the workflow's grants say now. `get_active`, so a
        deactivated account - whose membership row stays - no longer fires.
        """
        if exposure.execution_principal_user_id is None:
            return None
        membership = await member_repo.get_active(
            self.db,
            organization_id=exposure.organization_id,
            user_id=exposure.execution_principal_user_id,
        )
        if membership is None:
            return None
        user = await user_repo.get_by_id(self.db, exposure.execution_principal_user_id)
        if user is None or not user.is_active:
            return None
        # Only to admit the run: each step's own context is built when it is
        # dispatched, from the principal the run row records.
        ctx = AuthContext(
            user_id=exposure.execution_principal_user_id,
            organization_id=exposure.organization_id,
            role=membership.role,
            is_app_admin=user.is_app_admin,
        )
        workflow = await workflow_repo.get(
            self.db, exposure.workflow_id, organization_id=exposure.organization_id
        )
        if (
            workflow is None
            or workflow.status == WorkflowStatus.ARCHIVED.value
            or not await resolve_access(
                self.db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
            )
        ):
            return None
        version = cast(
            WorkflowVersion,
            await workflow_repo.get_version(
                self.db, exposure.workflow_version_id, organization_id=exposure.organization_id
            ),
        )
        return ctx, workflow, version

    async def _last_run_live(self, exposure: WorkflowExposure) -> bool:
        if exposure.last_run_id is None:
            return False
        run = await workflow_run_repo.get_run(
            self.db, exposure.last_run_id, organization_id=exposure.organization_id
        )
        return run is not None and run.status not in _TERMINAL

    async def _disable(self, exposure: WorkflowExposure) -> None:
        """Switch off a schedule nobody can run, and say so in the audit trail."""
        await workflow_exposure_repo.update(
            self.db, exposure=exposure, update_data={"is_active": False}
        )
        await record_audit(
            self.db,
            actor_user_id=None,
            organization_id=exposure.organization_id,
            action="workflow.exposure_disabled",
            target_type="workflow",
            target_id=str(exposure.workflow_id),
            details={"exposure_id": str(exposure.id), "reason": "principal_cannot_run"},
        )
        logger.warning("workflow_exposure_disabled", extra={"exposure_id": str(exposure.id)})

    async def _workflow(self, ctx: AuthContext, workflow_id: UUID, perm: Perm) -> Workflow:
        workflow = await workflow_repo.get(
            self.db, workflow_id, organization_id=ctx.organization_id
        )
        if workflow is None or not await resolve_access(
            self.db, ctx, workflow, perm, resource_type=WORKFLOW
        ):
            raise NotFoundError(message="Workflow not found", details={"workflow_id": workflow_id})
        return workflow

    async def _editable(self, ctx: AuthContext, workflow_id: UUID) -> Workflow:
        """The workflow, if this caller may edit it and run it, and it is not archived."""
        workflow = await self._workflow(ctx, workflow_id, Perm.WORKFLOWS_EDIT)
        if workflow.status == WorkflowStatus.ARCHIVED.value:
            raise WorkflowArchivedError(
                workflow_id=workflow.id, message="This workflow is archived"
            )
        if not await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
        ):
            raise AuthorizationError(
                message="A webhook or schedule runs as you, so you need to be able to run it",
                details={"workflow_id": str(workflow_id)},
            )
        return workflow

    async def _reusable(
        self, ctx: AuthContext, workflow: Workflow, node_id: UUID, adapter: ExposureAdapter
    ) -> WorkflowExposure | None:
        """The workflow's exposure if it is this node's, of this kind - else none,
        after removing whatever other trigger's exposure the workflow had."""
        require_human_publisher(ctx)
        exposure = await workflow_exposure_repo.get_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        if exposure is None:
            return None
        if exposure.node_instance_id == node_id and exposure.adapter == adapter.value:
            return exposure
        await self._remove(ctx, exposure)
        return None

    async def _remove(self, ctx: AuthContext, exposure: WorkflowExposure) -> None:
        await self._unregister_github(ctx, exposure)
        await self._audit(ctx, exposure, "workflow.exposure_deleted")
        await workflow_exposure_repo.delete(self.db, exposure=exposure)

    @staticmethod
    def _secret_of(exposure: WorkflowExposure) -> str:
        """A webhook's or a GitHub hook's signing secret, unsealed for its organization.

        The shape CHECK guarantees both columns on those two adapters.
        """
        return unseal(
            cast(str, exposure.secret_encrypted),
            scope=VaultScope.organization(exposure.organization_id),
            key_version=cast(int, exposure.secret_key_version),
        )

    async def _github_config(self, exposure: WorkflowExposure) -> GithubTriggerConfig:
        """The GitHub trigger's configuration, as the version the exposure runs has it."""
        version = cast(
            WorkflowVersion,
            await workflow_repo.get_version(
                self.db, exposure.workflow_version_id, organization_id=exposure.organization_id
            ),
        )
        node = WorkflowGraph.model_validate(version.graph).node_by_id[exposure.node_instance_id]
        return GithubTriggerConfig.model_validate(node.config)

    async def _register_github(
        self,
        ctx: AuthContext,
        exposure: WorkflowExposure,
        config: GithubTriggerConfig,
        secret: str,
    ) -> bool:
        """Register the hook on the repository through the connected account, or not.

        Whatever hook the account registered before is taken down first, so a
        change of repository or events never leaves a second one delivering.
        `False` - no account, no permission to manage webhooks, a repository it
        cannot reach, GitHub down - leaves the hook to be pasted by hand.
        """
        await self._unregister_github(ctx, exposure)
        portal = portal_catalog.get_portal(_GITHUB_PORTAL)
        adapter = portals.get_adapter(_GITHUB_PORTAL)
        if not config.register_with_account or portal is None or adapter is None:
            return False
        connection = await mcp_connection_repo.get_org_scoped_by_catalog_key(
            self.db,
            organization_id=exposure.organization_id,
            catalog_key=portal.mcp_catalog_key or _GITHUB_PORTAL,
        )
        if connection is None:
            return False
        token = await McpConnectionService(self.db).webhook_access_token(
            ctx, connection.id, required_scopes=portal.webhook_admin_scopes
        )
        if token is None:
            return False
        try:
            registered = await adapter.register_webhook(
                access_token=token,
                target=config.repository,
                webhook_url=cast(str, delivery_url(ExposureAdapter.GITHUB, exposure.id)),
                secret=secret,
                events=config.events,
            )
        except portals.PortalError:
            logger.info("workflow_github_hook_manual", extra={"exposure_id": str(exposure.id)})
            return False
        await workflow_exposure_repo.update(
            self.db,
            exposure=exposure,
            update_data={
                "connection_id": connection.id,
                "provider_target": config.repository,
                "provider_webhook_id": registered.provider_webhook_id,
            },
        )
        return True

    async def _unregister_github(self, ctx: AuthContext, exposure: WorkflowExposure) -> None:
        """Take down the hook the account registered, best-effort.

        Never stops what called it: a hook left behind answers 404 from here on,
        which is harmless, and a publish that failed because GitHub is down is not.
        """
        if exposure.provider_webhook_id is None:
            return
        adapter = portals.get_adapter(_GITHUB_PORTAL)
        portal = portal_catalog.get_portal(_GITHUB_PORTAL)
        try:
            if adapter is not None and portal is not None and exposure.connection_id is not None:
                token = await McpConnectionService(self.db).webhook_access_token(
                    ctx, exposure.connection_id, required_scopes=portal.webhook_admin_scopes
                )
                if token is not None:
                    await adapter.delete_webhook(
                        access_token=token,
                        target=exposure.provider_target,
                        provider_webhook_id=exposure.provider_webhook_id,
                    )
        except Exception:
            logger.warning(
                "workflow_github_hook_left_behind", extra={"exposure_id": str(exposure.id)}
            )
        await workflow_exposure_repo.update(
            self.db,
            exposure=exposure,
            update_data={
                "connection_id": None,
                "provider_target": None,
                "provider_webhook_id": None,
            },
        )

    async def _exposure(
        self, ctx: AuthContext, workflow: Workflow, exposure_id: UUID
    ) -> WorkflowExposure:
        exposure = await workflow_exposure_repo.get(
            self.db, exposure_id, organization_id=ctx.organization_id, workflow_id=workflow.id
        )
        if exposure is None:
            raise NotFoundError(
                message="Trigger not found", details={"exposure_id": str(exposure_id)}
            )
        return exposure

    async def _version_number(self, exposure: WorkflowExposure) -> int:
        version = cast(
            WorkflowVersion,
            await workflow_repo.get_version(
                self.db, exposure.workflow_version_id, organization_id=exposure.organization_id
            ),
        )
        return version.version

    async def _audit(
        self, ctx: AuthContext, exposure: WorkflowExposure, action: str, **details: Any
    ) -> None:
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=action,
            target_type="workflow",
            target_id=str(exposure.workflow_id),
            details={"exposure_id": str(exposure.id), "adapter": exposure.adapter, **details},
        )


__all__ = ["WorkflowExposureService"]
