"""`WorkflowExposureService` - a workflow's webhooks and schedules (#1792).

Setting one up is an editor's job, and it runs as whoever set it up: creating,
changing and removing need `workflows:edit` on the workflow, and the member doing
it must be able to run it too, since every fire acts with their authority. That
authority is read afresh on every fire - a member who has since lost the
workflow, or left, stops the webhook answering and the schedule firing.

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
    WorkflowExposureCreate,
    WorkflowExposureCreated,
    WorkflowExposureList,
    WorkflowExposureRead,
    WorkflowExposureUpdate,
)
from app.services import trigger_events
from app.services.access import WORKFLOW, resolve_access
from app.services.agent_trigger import _next_fire
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowNotRunnableError,
    WorkflowRunInputTooLargeError,
)
from app.services.workflow_execution.facade import WorkflowExecutionService
from app.services.workflow_registry import WorkflowArchivedError

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
        name=exposure.name,
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

    async def list_for_workflow(self, ctx: AuthContext, workflow_id: UUID) -> WorkflowExposureList:
        """Every exposure of a workflow this caller may view."""
        workflow = await self._workflow(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        exposures = await workflow_exposure_repo.list_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        return WorkflowExposureList(
            items=[_read(exposure, await self._version_number(exposure)) for exposure in exposures]
        )

    async def create(
        self, ctx: AuthContext, workflow_id: UUID, data: WorkflowExposureCreate
    ) -> WorkflowExposureCreated:
        """A new webhook or schedule on the workflow's current published version.

        A webhook's signing secret is minted here and returned this once.

        Raises:
            NotFoundError: The workflow does not exist, or this caller may not
                edit it.
            AuthorizationError: The caller may edit it but not run it - the
                authority every fire would act with.
            WorkflowArchivedError: The workflow is archived.
            WorkflowNotRunnableError: It has never been published.
        """
        workflow = await self._editable(ctx, workflow_id)
        if workflow.current_version_id is None:
            raise WorkflowNotRunnableError(workflow_id=workflow.id)
        now = datetime.now(UTC)
        secret: str | None = None
        fields: dict[str, Any] = {}
        if data.adapter is ExposureAdapter.WEBHOOK:
            secret = secrets.token_urlsafe(32)
            sealed = seal(secret, scope=VaultScope.organization(ctx.organization_id))
            fields = {
                "secret_encrypted": sealed.ciphertext,
                "secret_key_version": sealed.key_version,
            }
        else:
            kind = cast(ExposureScheduleKind, data.schedule_kind)
            fields = {
                "schedule_kind": kind.value,
                "interval_seconds": data.interval_seconds,
                "cron_expression": data.cron_expression,
                "next_fire_at": _next_fire(
                    schedule_kind=kind.value,
                    interval_seconds=data.interval_seconds,
                    cron_expression=data.cron_expression,
                    now=now,
                ),
            }
        exposure = await workflow_exposure_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            workflow_version_id=workflow.current_version_id,
            adapter=data.adapter.value,
            name=data.name,
            execution_principal_user_id=ctx.subject_id,
            is_active=True,
            run_input=data.run_input,
            **fields,
        )
        await self._audit(ctx, exposure, "workflow.exposure_created")
        return WorkflowExposureCreated(
            **_read(exposure, await self._version_number(exposure)).model_dump(),
            reveal_secret=secret,
        )

    async def update(
        self, ctx: AuthContext, workflow_id: UUID, exposure_id: UUID, data: WorkflowExposureUpdate
    ) -> WorkflowExposureRead:
        """Pause, rename, retime, re-input, or move an exposure to the live version.

        Whoever changes an exposure becomes the member it runs as: they decided
        what it does from now on, so it acts with their authority, not with that
        of whoever set it up.

        Raises:
            NotFoundError: The workflow or the exposure is not reachable.
            AuthorizationError: The caller may edit the workflow but not run it.
            WorkflowArchivedError: The workflow is archived.
            BadRequestError: A cadence change on a webhook.
            WorkflowNotRunnableError: `pin_current_version` on a workflow with
                no published version.
        """
        workflow = await self._editable(ctx, workflow_id)
        exposure = await self._exposure(ctx, workflow, exposure_id)
        changes: dict[str, Any] = {"execution_principal_user_id": ctx.subject_id}
        # Sent as null, a name is cleared and the row falls back to its default label.
        if "name" in data.model_fields_set:
            changes["name"] = data.name
        if data.is_active is not None:
            changes["is_active"] = data.is_active
        if data.run_input is not None:
            changes["run_input"] = data.run_input
        if data.pin_current_version:
            if workflow.current_version_id is None:
                raise WorkflowNotRunnableError(workflow_id=workflow.id)
            changes["workflow_version_id"] = workflow.current_version_id
        if data.schedule_kind is not None:
            if exposure.adapter != ExposureAdapter.SCHEDULE.value:
                raise BadRequestError(
                    message="Only a schedule has a cadence",
                    details={"exposure_id": str(exposure.id)},
                )
            changes["schedule_kind"] = data.schedule_kind.value
            changes["interval_seconds"] = data.interval_seconds
            changes["cron_expression"] = data.cron_expression
        # A schedule's clock restarts from now whenever its cadence changes or it
        # resumes: a paused schedule does not owe the runs it missed.
        resumed = data.is_active is True and not exposure.is_active
        if exposure.adapter == ExposureAdapter.SCHEDULE.value and (
            data.schedule_kind is not None or resumed
        ):
            changes["next_fire_at"] = _next_fire(
                schedule_kind=changes.get("schedule_kind", exposure.schedule_kind),
                interval_seconds=changes.get("interval_seconds", exposure.interval_seconds),
                cron_expression=changes.get("cron_expression", exposure.cron_expression),
                now=datetime.now(UTC),
            )
        exposure = await workflow_exposure_repo.update(
            self.db, exposure=exposure, update_data=changes
        )
        await self._audit(
            ctx,
            exposure,
            "workflow.exposure_updated",
            changed=sorted(key for key in changes if key != "execution_principal_user_id"),
        )
        return _read(exposure, await self._version_number(exposure))

    async def delete(self, ctx: AuthContext, workflow_id: UUID, exposure_id: UUID) -> None:
        """Remove an exposure. Runs it already admitted keep going.

        Raises:
            NotFoundError: The workflow or the exposure is not reachable.
            AuthorizationError: The caller may edit the workflow but not run it.
            WorkflowArchivedError: The workflow is archived.
        """
        workflow = await self._editable(ctx, workflow_id)
        exposure = await self._exposure(ctx, workflow, exposure_id)
        await self._audit(ctx, exposure, "workflow.exposure_deleted")
        await workflow_exposure_repo.delete(self.db, exposure=exposure)

    async def rotate_secret(
        self, ctx: AuthContext, workflow_id: UUID, exposure_id: UUID
    ) -> WorkflowExposureCreated:
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
                "execution_principal_user_id": ctx.subject_id,
            },
        )
        await self._audit(ctx, exposure, "workflow.exposure_secret_rotated")
        return WorkflowExposureCreated(
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
            ctx, workflow, version, triggered_by=WorkflowRunTrigger.WEBHOOK, run_input=payload
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
                        run_input=exposure.run_input,
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
