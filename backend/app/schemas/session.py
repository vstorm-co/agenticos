"""Session schemas."""

from datetime import datetime
from uuid import UUID

from app.schemas.base import BaseSchema


class SessionRead(BaseSchema):
    """Session response schema."""

    id: UUID
    device_name: str | None = None
    device_type: str | None = None
    ip_address: str | None = None
    is_current: bool = False
    created_at: datetime
    last_used_at: datetime


class SessionListResponse(BaseSchema):
    """One page of a user's sessions.

    ``items``/``total`` rather than the ``sessions`` key this used to return, so
    it pages like every other list in the API. ``total`` counts the user's
    sessions, not the page - the client needs it to know there is a next one.
    """

    items: list[SessionRead]
    total: int


class LogoutAllResponse(BaseSchema):
    """Response for logout all sessions."""

    message: str
    sessions_logged_out: int
