"""Session schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

AppPlatform = Literal["macos", "windows", "linux", "ios", "android"]


class SessionRead(BaseSchema):
    """Session response schema."""

    id: UUID
    device_name: str | None = None
    device_type: str | None = None
    ip_address: str | None = None
    is_current: bool = False
    app_platform: str | None = None
    """The AgenticOS app this session signed in through (`AppPlatform`), or null
    for a browser. Validated where it is written, `SessionAppUpdate`."""
    app_version: str | None = None
    created_at: datetime
    last_used_at: datetime


class SessionAppUpdate(BaseSchema):
    """What the console tells the server when it is loaded inside an AgenticOS app."""

    platform: AppPlatform
    version: str = Field(min_length=1, max_length=32, pattern=r"^[0-9A-Za-z.+-]+$")


class SessionListResponse(BaseSchema):
    """One page of a user's sessions.

    `items`/`total` rather than the `sessions` key this used to return, so
    it pages like every other list in the API. `total` counts the user's
    sessions, not the page - the client needs it to know there is a next one.
    """

    items: list[SessionRead]
    total: int


class LogoutAllResponse(BaseSchema):
    """Response for logout all sessions."""

    message: str
    sessions_logged_out: int
