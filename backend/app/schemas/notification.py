"""Schemas for the notification inbox (#1598)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, ValidationError

from app.db.models.notification import Notification, NotificationChannel, NotificationEventType
from app.db.models.notification_delivery import NotificationDelivery
from app.schemas.base import BaseSchema


class NotificationAgent(BaseSchema):
    """The agent a notification is about, as much as the bell needs to draw its face."""

    id: UUID
    slug: str
    name: str
    has_avatar: bool = False
    avatar_color: int | None = None


def _agent_of(context: dict[str, Any] | None) -> NotificationAgent | None:
    """The agent a row's render context names, or `None` for one about no agent.

    Rows written before the face was kept carry only the name, and draw the
    icon for their kind instead.
    """
    if not context or "agent_id" not in context:
        return None
    try:
        return NotificationAgent(
            id=context["agent_id"],
            slug=context.get("agent_slug", ""),
            name=context.get("agent_name", ""),
            has_avatar=bool(context.get("agent_has_avatar")),
            avatar_color=context.get("agent_avatar_color"),
        )
    except ValidationError:
        return None


class NotificationRead(BaseSchema):
    """One inbox row - `render_context` itself never leaves the service layer."""

    id: UUID
    event_type: str
    summary: str
    context_url: str | None = None
    read_at: datetime | None = None
    created_at: datetime
    agent: NotificationAgent | None = Field(
        default=None,
        description="The agent the row is about, for its face; null for a row about none.",
    )

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
            agent=_agent_of(notification.render_context),
        )


class NotificationList(BaseSchema):
    items: list[NotificationRead]
    next_cursor: str | None = None


class UnreadCountRead(BaseSchema):
    """How many unread rows the caller can see.

    `approximate` is true when the scan behind the count stopped on its own
    bound with rows still behind it: the count is a floor rather than a total.
    Without it, a capped answer and an exact one are the same number (#1761).
    """

    count: int
    approximate: bool = False


class MarkAllReadResult(BaseSchema):
    """How many rows one "mark all read" marked, and where to carry on from.

    `marked` is what this request changed, not what it looked at, so two
    overlapping sweeps cannot both claim the same rows.

    `remaining` is true when the sweep ran out of scan rather than out of
    inbox, so a caller that treats `marked` as "the inbox is now clear" would
    hide the button that finishes the job. `next_cursor` is what finishes it:
    pass it back and the next sweep starts past the window this one covered,
    which is what gets a caller past a run of rows the read-time gate hides -
    those are never marked on their behalf, because the gate reads current
    permissions and a restored role would find them already read.
    """

    marked: int
    remaining: bool = False
    next_cursor: str | None = None


class ClearInboxResult(BaseSchema):
    """How many rows one "clear" actually took out of the inbox.

    A number rather than a 204, and for the reason `MarkAllReadResult` carries
    one: the sweep is capped, so a caller has to be able to tell an emptied
    inbox from a truncated one and ask again.
    """

    cleared: int


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
