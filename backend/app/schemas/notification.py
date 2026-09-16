"""Schemas for the notification inbox (#1598)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.db.models.notification import Notification
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
