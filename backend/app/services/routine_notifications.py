"""Live routine delivery limits, shared by notification creation and retry delivery."""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.notification import NotificationChannel
from app.repositories import agent_trigger_repo, watch_repo
from app.schemas.routine_notifications import ExternalNotificationChannel, read_channels


def channels(
    selection: list[ExternalNotificationChannel] | None,
) -> set[NotificationChannel] | None:
    """None inherits; an empty list keeps frontend delivery and disables external channels."""
    if selection is None:
        return None
    return {NotificationChannel.IN_APP, *(NotificationChannel(item) for item in selection)}


async def allowed_channels(
    db: AsyncSession,
    *,
    organization_id: UUID | None,
    recipient_user_id: UUID,
    context: Mapping[str, object] | None,
) -> set[NotificationChannel] | None:
    """Resolve the owning person's current limit without changing another recipient's policy.

    The reference comes from the notification producer, never a request parameter.
    Deletion, pause or invalid scope prevents pending external sends. Preferences
    and organization-mandatory alerts retain their own independent enforcement.
    """
    if context is None or "routine_origin_id" not in context:
        return None
    raw, kind = context.get("routine_origin_id"), context.get("routine_kind")
    if not isinstance(raw, str) or kind not in ("watch", "trigger"):
        return set()
    try:
        origin = UUID(raw)
    except ValueError:
        return set()
    if kind == "watch":
        watch = await watch_repo.get_by_id(db, origin, fresh=True)
        if watch is None or watch.organization_id != organization_id:
            return set()
        owner, active, selected, end, stopped = (
            watch.user_id,
            watch.is_active,
            watch.notification_channels,
            watch.ends_at,
            watch.auto_stopped_at,
        )
    else:
        trigger = await agent_trigger_repo.get_by_id(db, origin, fresh=True)
        if trigger is None or trigger.organization_id != organization_id:
            return set()
        owner, active, selected, end, stopped = (
            trigger.created_by_user_id,
            trigger.is_active,
            trigger.notification_channels,
            trigger.ends_at,
            trigger.auto_stopped_at,
        )
    if owner != recipient_user_id:
        return None
    if end is not None and end <= datetime.now(UTC):
        return {NotificationChannel.IN_APP}
    if "routine_auto_stopped_at" in context:
        if (
            active
            or stopped is None
            or context["routine_auto_stopped_at"] != stopped.isoformat()
            or context.get("routine_failure_reason") not in ("run", "check")
        ):
            return {NotificationChannel.IN_APP}
    elif not active:
        return {NotificationChannel.IN_APP}
    return channels(read_channels(selected))
