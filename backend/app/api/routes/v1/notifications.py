"""The notification inbox, and the deployment's own failed-delivery view (#1598).

Every signed-in caller has an inbox, regardless of role - the first four routes
read and write only the caller's own `recipient_user_id`. What each row *shows*
is still gate-checked (`docs/design/notification-center-plan.md`, Decision 7),
inside the service, not at the route layer.

The failed-deliveries view is the other shape entirely: `CurrentAppAdmin`-gated,
deployment-wide, and diagnostic - a permanent send failure is an operational
concern, not a tenant one (Decision 3).
"""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import Auth, CurrentAppAdmin, NotificationCenterSvc, NotificationDeliverySvc
from app.schemas.notification import (
    FailedDeliveryList,
    FailedDeliveryRead,
    MarkAllReadResult,
    NotificationList,
    NotificationPreferenceList,
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationRead,
    UnreadCountRead,
)
from app.services.notification_center import PreferenceItem, decode_cursor, encode_cursor

router = APIRouter()


@router.get("/notifications", response_model=NotificationList)
async def list_notifications(
    service: NotificationCenterSvc,
    ctx: Auth,
    cursor: str | None = Query(None, description="Opaque page token from a previous response"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """The caller's own inbox, newest first, gate-filtered (Decision 7)."""
    after = decode_cursor(cursor) if cursor else None
    rows, gates = await service.list_inbox(ctx, after=after, limit=limit)
    items = [
        NotificationRead.from_row(
            row,
            strip_context_url=gates[row.id].strip_context_url,
            summary_override=gates[row.id].summary_override,
        )
        for row in rows
    ]
    next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if len(rows) == limit else None
    return NotificationList(items=items, next_cursor=next_cursor)


@router.get("/notifications/unread-count", response_model=UnreadCountRead)
async def unread_notification_count(service: NotificationCenterSvc, ctx: Auth) -> Any:
    return UnreadCountRead(count=await service.unread_count(ctx))


@router.get("/notifications/preferences", response_model=NotificationPreferenceList)
async def list_notification_preferences(service: NotificationCenterSvc, ctx: Auth) -> Any:
    """Every `(event_type, channel)` pair the caller may toggle (Decision 4) -
    a mandatory event type or one of the four legacy-column pairs is never
    in this list, because there is no preference to show for it."""
    items = await service.list_preferences(ctx)
    return NotificationPreferenceList(
        items=[
            NotificationPreferenceRead(
                event_type=item.event_type.value, channel=item.channel.value, enabled=item.enabled
            )
            for item in items
        ]
    )


@router.patch("/notifications/preferences", response_model=NotificationPreferenceRead)
async def update_notification_preference(
    data: NotificationPreferenceUpdate, service: NotificationCenterSvc, ctx: Auth
) -> Any:
    """Upsert one pair. 400s a mandatory event type or a legacy-column pair -
    the same refusal `list_notification_preferences` expresses by omission."""
    item: PreferenceItem = await service.update_preference(
        ctx, event_type=data.event_type, channel=data.channel, enabled=data.enabled
    )
    return NotificationPreferenceRead(
        event_type=item.event_type.value, channel=item.channel.value, enabled=item.enabled
    )


@router.patch("/notifications/{notification_id}", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: UUID, service: NotificationCenterSvc, ctx: Auth
) -> Any:
    """Mark one of the caller's own rows read. 404s a row they may not (or may
    no longer) see - the same rule a cross-tenant resource already follows.

    Registered after `PATCH /notifications/preferences`: Starlette matches
    path routes in registration order, and `{notification_id}` would
    otherwise swallow `preferences` as its own path parameter.
    """
    notification, gate = await service.mark_one_read(ctx, notification_id)
    return NotificationRead.from_row(
        notification,
        strip_context_url=gate.strip_context_url,
        summary_override=gate.summary_override,
    )


@router.post("/notifications/mark-all-read", response_model=MarkAllReadResult)
async def mark_all_notifications_read(service: NotificationCenterSvc, ctx: Auth) -> Any:
    return MarkAllReadResult(marked=await service.mark_all_read(ctx))


@router.get("/admin/notifications/deliveries", response_model=FailedDeliveryList)
async def list_failed_notification_deliveries(
    service: NotificationDeliverySvc,
    _user: CurrentAppAdmin,
    status: Literal["failed"] = Query(
        "failed", description="Only terminally failed deliveries are listed today"
    ),
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """Deliveries that exhausted their retries, deployment-wide, newest first."""
    rows, total = await service.list_failed(skip=skip, limit=limit)
    items = [FailedDeliveryRead.from_row(delivery, notification) for delivery, notification in rows]
    return FailedDeliveryList(items=items, total=total)
