"""Pre-model admission for a routine's explicitly approved local folder.

Only a readiness check can raise RoutineDeviceOffline. A lost/uncertain file or
shell operation after execution starts must never become an automatic new run.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError
from app.core.permissions import AuthContext
from app.db.models.agent_trigger import AgentTrigger
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
        raise RoutineDeviceOffline(message="Waiting for this routine's signed-in computer")
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
        raise RoutineDeviceOffline(
            message="Waiting for a signed-in computer to confirm this routine's folder permission",
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


async def follow_signed_in_session(
    db: AsyncSession, trigger: AgentTrigger, ctx: AuthContext
) -> None:
    """Point a routine's computer at the person's current desktop session.

    A routine remembers the session its folder was approved on. Signing in to the
    app again starts a new one, and the routine would wait on a session that is
    gone. When that session has ended and the person's app is connected now, the
    routine moves to a connected session that confirms its grant. Whether it may
    work there is still the app's decision: a permission for every routine of the person
    survives a new sign-in, a permission for one routine does not, and that
    routine is then blocked for review as before.
    """
    if trigger.local_target is None or not trigger.runs_as_creator:
        return
    try:
        local = LocalTarget.model_validate(trigger.local_target)
    except ValidationError:
        return  # Admission blocks it for review, with the reason, as before.
    user_id = trigger.created_by_user_id
    if local.routine_grant is None or local.device_id is None or user_id is None:
        return
    if (
        ctx.user_id != user_id
        or ctx.organization_id != trigger.organization_id
        or ctx.routine_id != trigger.id
    ):
        raise AuthorizationError(message="Only this routine's owner can rebind its computer")
    now = datetime.now(UTC)
    if await session_repo.active_device(db, session_id=local.device_id, user_id=user_id, now=now):
        return
    previous_intent = activation_intent(trigger)
    refused = False
    transient = False
    for device in await device_hub.connected(user_id):
        moved = local.model_copy(update={"device_id": device.session_id})
        try:
            await ready(db, ctx, moved)
        except RoutineDeviceOffline:
            transient = True
            continue
        except RoutineLocalConsentRequired:
            refused = True
            continue
        locked = await agent_trigger_repo.get(
            db, trigger.id, organization_id=trigger.organization_id, for_update=True
        )
        if (
            locked is None
            or locked.created_by_user_id != user_id
            or not locked.runs_as_creator
            or activation_intent(locked) != previous_intent
        ):
            return
        locked.local_target = moved.model_dump(mode="json")
        await device_wait_repo.rebind_device(
            db,
            trigger_id=locked.id,
            user_id=user_id,
            previous_device_id=local.device_id,
            device_id=device.session_id,
            previous_intent=previous_intent,
            intent=activation_intent(locked),
        )
        await db.flush()
        return
    if refused and not transient:
        raise RoutineLocalConsentRequired(
            message="Connected computers refused this routine's grant; review its folder permission"
        )
