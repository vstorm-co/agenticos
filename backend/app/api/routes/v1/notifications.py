"""The notification inbox: a caller's own rows, nothing gated on a `Perm` (#1598).

Every signed-in caller has an inbox, regardless of role - these four routes read
and write only the caller's own `recipient_user_id`. What each row *shows* is
still gate-checked (`docs/design/notification-center-plan.md`, Decision 7),
inside the service, not at the route layer.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import Auth, NotificationCenterSvc
from app.schemas.notification import (
    MarkAllReadResult,
    NotificationList,
    NotificationRead,
    UnreadCountRead,
)
from app.services.notification_center import decode_cursor, encode_cursor

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


@router.patch("/notifications/{notification_id}", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: UUID, service: NotificationCenterSvc, ctx: Auth
) -> Any:
    """Mark one of the caller's own rows read. 404s a row they may not (or may
    no longer) see - the same rule a cross-tenant resource already follows."""
    notification, gate = await service.mark_one_read(ctx, notification_id)
    return NotificationRead.from_row(
        notification,
        strip_context_url=gate.strip_context_url,
        summary_override=gate.summary_override,
    )


@router.post("/notifications/mark-all-read", response_model=MarkAllReadResult)
async def mark_all_notifications_read(service: NotificationCenterSvc, ctx: Auth) -> Any:
    return MarkAllReadResult(marked=await service.mark_all_read(ctx))
