"""`WorkflowExposureService` - a workflow's webhook or schedule (#1792).

A workflow that starts from a webhook or a schedule trigger node gets its
exposure when a version is published (`app.services.workflow_triggers`), and
runs as the member who published it. That authority is read afresh on every
fire - a member who has since lost the workflow, or left, stops the webhook
answering and the schedule firing. Pausing, resuming and rotating a webhook's
secret need `workflows:edit` and `workflows:run` on the workflow.

Firing ends in the one admission path every surface shares
(`WorkflowExecutionService.admit_pinned`), on the version the exposure pinned.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.vault import VaultScope, seal, unseal
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_exposure import (
    ExposureAdapter,
    ExposureScheduleKind,
    WorkflowExposure,
)
from app.db.models.workflow_run import WorkflowRunTrigger
from app.repositories import member_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_exposure as workflow_exposure_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_exposure import (
    WebhookAdmitted,
    WorkflowExposureRead,
    WorkflowExposureUpdate,
    WorkflowExposureWithSecret,
)
from app.services import trigger_events
from app.services.access import WORKFLOW, resolve_access
from app.services.agent_trigger import _next_fire
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowArchivedError,
    WorkflowRunInputTooLargeError,
)
from app.services.workflow_execution.facade import WorkflowExecutionService
from app.workflows.nodes._triggers import ScheduleTriggerConfig

logger = logging.getLogger(__name__)

# The signed-delivery schemes a workflow webhook accepts: a relay signing with
# the generic headers, or GitHub's own. Both are HMAC-SHA256 over the raw body.
_SIGNED_SOURCES = ("webhook", "github")

# The run states a schedule waits behind rather than fire on top of.
_TERMINAL = {"succeeded", "failed", "cancelled", "budget_exceeded"}


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
        created_at=exposure.created_at,
        updated_at=exposure.updated_at,
    )


def _parse_body(body: bytes) -> dict[str, Any]:
    """A delivery's body as the JSON object its run starts with, or a 400."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BadRequestError(message="Webhook body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise BadRequestError(message="Webhook body must be a JSON object")
    return payload


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
        fields: dict[str, Any] = {
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
            or (exposure.schedule_kind, exposure.interval_seconds, exposure.cron_expression)
            != (config.schedule_kind, interval, cron)
        ):
            fields["next_fire_at"] = _next_fire(
                schedule_kind=config.schedule_kind,
                interval_seconds=interval,
                cron_expression=cron,
                now=now,
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
        changes: dict[str, Any] = {"is_active": data.is_active}
        if (
            data.is_active
            and not exposure.is_active
            and exposure.adapter == ExposureAdapter.SCHEDULE.value
        ):
            changes["next_fire_at"] = _next_fire(
                schedule_kind=cast(str, exposure.schedule_kind),
                interval_seconds=exposure.interval_seconds,
                cron_expression=exposure.cron_expression,
                now=datetime.now(UTC),
            )
        exposure = await workflow_exposure_repo.update(
            self.db, exposure=exposure, update_data=changes
        )
        await self._audit(
            ctx,
            exposure,
            "workflow.exposure_resumed" if data.is_active else "workflow.exposure_paused",
        )
        return _read(exposure, await self._version_number(exposure))

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
        if exposure.adapter != ExposureAdapter.WEBHOOK.value:
            raise BadRequestError(
                message="Only a webhook has a signing secret",
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
        return WorkflowExposureWithSecret(
            **_read(exposure, await self._version_number(exposure)).model_dump(),
            reveal_secret=secret,
        )

    async def receive_webhook(
        self, exposure_id: UUID, *, body: bytes, headers: Mapping[str, str]
    ) -> WebhookAdmitted:
        """Admit one signed delivery as one run, or answer with the run it already admitted.

        Called with no auth context: the delivery is authenticated by its HMAC
        against the exposure's own secret, and the run acts as the exposure's
        member. Every delivery must name itself (`X-Delivery-Id`, or GitHub's
        `X-GitHub-Delivery`); the id is recorded in the transaction that admits
        the run, so a retry of it - however late - returns the first run.

        Raises:
            NotFoundError: No active webhook has this id.
            AuthorizationError: The signature did not verify, or the member it
                runs as can no longer run the workflow.
            BadRequestError: No delivery id, or a body that is not a JSON object.
        """
        exposure = await workflow_exposure_repo.get_by_id(self.db, exposure_id)
        if (
            exposure is None
            or exposure.adapter != ExposureAdapter.WEBHOOK.value
            or not exposure.is_active
        ):
            raise NotFoundError(message="Webhook not found", details={"exposure_id": exposure_id})
        secret = unseal(
            cast(str, exposure.secret_encrypted),
            scope=VaultScope.organization(exposure.organization_id),
            key_version=cast(int, exposure.secret_key_version),
        )
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
        payload = _parse_body(body)

        await workflow_exposure_repo.lock_delivery(
            self.db, exposure_id=exposure.id, delivery_id=delivery_id
        )
        seen = await workflow_exposure_repo.get_delivery(
            self.db, exposure_id=exposure.id, delivery_id=delivery_id
        )
        if seen is not None:
            return WebhookAdmitted(run_id=seen.workflow_run_id, duplicate=True)

        fire = await self._fire_context(exposure)
        if fire is None:
            raise AuthorizationError(
                message="The member this webhook runs as can no longer run this workflow",
                details={"exposure_id": str(exposure_id)},
            )
        ctx, workflow, version = fire
        run, entry_node_run_id = await self.runs.admit_pinned(
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
        from app.worker.tasks.workflow_tasks import trigger_dispatch

        trigger_dispatch(self.db, workflow_run_id=run.id, node_run_id=entry_node_run_id)
        return WebhookAdmitted(run_id=run.id, duplicate=False)

    async def fire_due(self, *, now: datetime, limit: int = 100) -> list[tuple[UUID, UUID]]:
        """Fire every schedule due by `now`, and return what to dispatch.

        Each claimed schedule's clock advances in this transaction whatever
        happens next, so a tick is spent once: a schedule whose last run is still
        going skips it rather than stack a second run behind the first, and one
        whose run is refused (a quota, an oversized input) logs and waits for its
        next tick. A schedule whose member can no longer run it is switched off
        and audited - retrying against a wall every minute helps nobody.

        Returns `(run_id, entry_node_run_id)` for every admitted run; the caller
        submits their first dispatch after this transaction commits.
        """
        admitted: list[tuple[UUID, UUID]] = []
        for exposure in await workflow_exposure_repo.claim_due_schedules(
            self.db, now=now, limit=limit
        ):
            await workflow_exposure_repo.update(
                self.db,
                exposure=exposure,
                update_data={
                    "next_fire_at": _next_fire(
                        schedule_kind=cast(str, exposure.schedule_kind),
                        interval_seconds=exposure.interval_seconds,
                        cron_expression=exposure.cron_expression,
                        now=now,
                    )
                },
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
            except (WorkflowAdmissionQuotaError, WorkflowRunInputTooLargeError) as exc:
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
        # Only to admit the run: each step's own context is built when it is
        # dispatched, from the principal the run row records.
        ctx = AuthContext(
            user_id=exposure.execution_principal_user_id,
            organization_id=exposure.organization_id,
            role=membership.role,
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
        await self._audit(ctx, exposure, "workflow.exposure_deleted")
        await workflow_exposure_repo.delete(self.db, exposure=exposure)

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
