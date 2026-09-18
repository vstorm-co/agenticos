"""Schemas for the notification inbox (#1598)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.db.models.notification import Notification, NotificationChannel, NotificationEventType
from app.db.models.notification_delivery import NotificationDelivery
from app.schemas.base import BaseSchema


class NotificationRead(BaseSchema):
    """One inbox row - `render_context` never leaves the service layer."""

    id: UUID
    event_type: str
    summary: str
    context_url: str | None = None
    read_at: datetime | None = None
    created_at: datetime

    @classmethod
    def from_row(
        cls,
        notification: Notification,
        *,
        strip_context_url: bool,
        summary_override: str | None = None,
    ) -> NotificationRead:
        """Decision 7's degrade shape: the row is never rewritten, only what a
        reader without current `approvals:decide` is served from it changes -
        its `context_url` withheld, and its `summary` replaced with the same
        fact-only wording the email channel already sends that reader."""
        return cls(
            id=notification.id,
            event_type=notification.event_type,
            summary=summary_override or notification.summary,
            context_url=None if strip_context_url else notification.context_url,
            read_at=notification.read_at,
            created_at=notification.created_at,
        )


class NotificationList(BaseSchema):
    items: list[NotificationRead]
    next_cursor: str | None = None


class UnreadCountRead(BaseSchema):
    count: int


class MarkAllReadResult(BaseSchema):
    marked: int


class FailedDeliveryRead(BaseSchema):
    """One terminally failed delivery - the operational view, app-admin only.

    Never `render_context`: this is a diagnostic list of what did not send,
    not a way to read a notification's content out from under its recipient.
    """

    id: UUID
    notification_id: UUID
    event_type: str
    recipient_user_id: UUID
    channel: str
    attempts: int
    last_error: str | None = None
    created_at: datetime

    @classmethod
    def from_row(
        cls, delivery: NotificationDelivery, notification: Notification
    ) -> FailedDeliveryRead:
        return cls(
            id=delivery.id,
            notification_id=notification.id,
            event_type=notification.event_type,
            recipient_user_id=notification.recipient_user_id,
            channel=delivery.channel,
            attempts=delivery.attempts,
            last_error=delivery.last_error,
            created_at=delivery.created_at,
        )


class FailedDeliveryList(BaseSchema):
    items: list[FailedDeliveryRead]
    total: int


class NotificationPreferenceRead(BaseSchema):
    """One `(event_type, channel)` pair's current value (Decision 4).

    Only the pairs `NotificationCenterService`'s own `_TOGGLABLE_PAIRS`
    covers ever appear here - a mandatory event type or one of the four
    legacy-column pairs is never listed, because there is no preference to
    show.
    """

    event_type: str
    channel: str
    enabled: bool


class NotificationPreferenceList(BaseSchema):
    items: list[NotificationPreferenceRead]


class NotificationPreferenceUpdate(BaseSchema):
    event_type: NotificationEventType
    channel: NotificationChannel
    enabled: bool
