"""Pre-model admission for a routine's explicitly approved local folder.

Only a readiness check can raise RoutineDeviceOffline. A lost/uncertain file or
shell operation after execution starts must never become an automatic new run.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError
from app.core.permissions import AuthContext
from app.repositories import agent_trigger_repo, session_repo
from app.repositories import routine_device_wait as device_wait_repo
from app.schemas.local_target import LocalTarget, RoutineLocalScope
from app.services import device_hub
from app.services.routine_actions import activation_intent


class RoutineDeviceOffline(device_hub.DeviceUnavailable):
    """No local effect or model call has been admitted; durably wait for this device."""


class RoutineLocalConsentRequired(BadRequestError):
    """The desktop must explicitly review this routine's local authority."""


class RoutineActivationObsolete(ConflictError):
    """The original waiting activation no longer has authority; no model was called."""


async def admit_activation(db: AsyncSession, ctx: AuthContext) -> None:
    """Commit start with the first run, after preparation and before model/effects."""
    if ctx.routine_activation_id is None:
        return
    if ctx.routine_id is None or ctx.user_id is None:
        raise AuthorizationError(message="A device activation needs its original routine owner")
    trigger = await agent_trigger_repo.get(
        db, ctx.routine_id, organization_id=ctx.organization_id, for_update=True
    )
    wait = await device_wait_repo.get(db, ctx.routine_activation_id)
    if (
        wait is None
        or wait.organization_id != ctx.organization_id
        or wait.trigger_id != ctx.routine_id
        or wait.user_id != ctx.user_id
    ):
        raise AuthorizationError(message="The device activation belongs to another routine")
    if wait.status != "waiting":
        raise RoutineActivationObsolete(message="This device activation already settled")
    if (
        trigger is None
        or not trigger.is_active
        or not trigger.runs_as_creator
        or trigger.created_by_user_id != ctx.user_id
        or trigger.local_target is None
        or (trigger.ends_at is not None and trigger.ends_at <= datetime.now(UTC))
        or activation_intent(trigger) != wait.intent_hash
    ):
        await device_wait_repo.settle(
            db, activation_id=wait.id, status="cancelled", reason="routine_changed"
        )
        raise RoutineActivationObsolete(message="This device activation's authority changed")
    if (
        await session_repo.active_device(
            db, session_id=wait.device_id, user_id=ctx.user_id, now=datetime.now(UTC)
        )
        is None
    ):
        raise RoutineLocalConsentRequired(
            message="This routine's device was disconnected; review it again"
        )
    if not await device_wait_repo.settle(db, activation_id=wait.id, status="started"):
        raise RoutineActivationObsolete(message="This device activation already settled")


class _Ready(BaseModel):
    allowed: bool = Field(strict=True)


def local_scope(ctx: AuthContext, local: LocalTarget) -> RoutineLocalScope | None:
    if ctx.routine_id is None:
        if local.routine_grant is not None:
            raise AuthorizationError(message="A routine folder grant cannot be used by another run")
        return None
    if ctx.user_id is None or ctx.fired_as_creator is None or ctx.subject_is_publisher_fallback:
        raise AuthorizationError(message="Only a routine acting as its owner can use its computer")
    try:
        return local.routine_scope(
            organization_id=ctx.organization_id, routine_id=ctx.routine_id, user_id=ctx.user_id
        )
    except ValueError as exc:
        raise RoutineLocalConsentRequired(
            message="Review this routine's device, folder and operations on the desktop app",
            details={"routine_id": ctx.routine_id},
        ) from exc


async def ready(db: AsyncSession, ctx: AuthContext, local: LocalTarget) -> device_hub.Device:
    """Check the exact paired session and consent before opening a paid run."""
    scope = local_scope(ctx, local)
    if scope is None:
        raise AuthorizationError(message="Routine admission needs a routine context")
    if (
        await session_repo.active_device(
            db, session_id=scope.device_id, user_id=scope.user_id, now=datetime.now(UTC)
        )
        is None
    ):
        raise RoutineLocalConsentRequired(
            message="This routine's device session was disconnected; link and approve it again",
            details={"routine_id": scope.routine_id},
        )
    device = await device_hub.wait_for(scope.user_id, scope.device_id, timeout=0)
    if device is None:
        raise RoutineDeviceOffline(
            message="Waiting for this routine's approved computer",
            details={"device_id": scope.device_id, "routine_id": scope.routine_id},
        )
    if (
        device.user_id != scope.user_id
        or device.session_id != scope.device_id
        or not device.capabilities.routine_grants
        or local.mode not in device.capabilities.sandbox_modes
    ):
        raise RoutineLocalConsentRequired(
            message="Update the desktop app and review this routine's folder permission",
            details={"routine_id": scope.routine_id},
        )
    try:
        result = await device_hub.call(
            scope.device_id,
            "routine.check",
            {
                "root": local.folder,
                "mode": local.mode,
                "work_context": scope.model_dump(mode="json"),
            },
            timeout=10,
        )
    except (device_hub.DeviceUnavailable, device_hub.DeviceCallTimedOut) as exc:
        # This RPC has no effects. No model or filesystem operation is retried here.
        raise RoutineDeviceOffline(
            message="Waiting for this routine's computer to confirm its folder permission",
            details={"device_id": scope.device_id, "routine_id": scope.routine_id},
        ) from exc
    except device_hub.DeviceCallFailed as exc:
        raise RoutineLocalConsentRequired(
            message="Review this routine's folder permission on its approved computer",
            details={"routine_id": scope.routine_id},
        ) from exc
    try:
        confirmed = _Ready.model_validate(result)
    except ValidationError as exc:
        raise RoutineLocalConsentRequired(
            message="The desktop did not confirm this routine's permission; update it and review again",
            details={"routine_id": scope.routine_id},
        ) from exc
    if not confirmed.allowed:
        raise RoutineLocalConsentRequired(
            message="This routine's folder permission is no longer active",
            details={"routine_id": scope.routine_id},
        )
    return device
