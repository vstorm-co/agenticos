"""Personal opt-in destinations; transport identifiers and secrets stay private."""

from typing import Literal
from uuid import UUID

from app.schemas.base import BaseSchema

ChatNotificationChannel = Literal[
    "slack", "telegram", "mattermost", "teams", "sms", "imessage", "discord"
]


class NotificationDestinationRead(BaseSchema):
    session_id: UUID
    channel: ChatNotificationChannel
    bot_name: str
    account_name: str


class NotificationRouteRead(BaseSchema):
    id: UUID
    channel: ChatNotificationChannel
    session_id: UUID
    available: bool


class NotificationRouteList(BaseSchema):
    items: list[NotificationRouteRead]
    destinations: list[NotificationDestinationRead]


class NotificationRouteUpdate(BaseSchema):
    channel: ChatNotificationChannel
    session_id: UUID | None
