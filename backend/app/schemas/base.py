"""Base Pydantic schemas."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict


def serialize_datetime(dt: datetime) -> str:
    """Serialize datetime to ISO format with timezone.

    Ensures all datetimes have explicit timezone (defaults to UTC).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.isoformat()


class BaseSchema(BaseModel):
    """Base schema with common configuration."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        json_encoders={datetime: serialize_datetime},
    )


class TimestampSchema(BaseModel):
    """Schema with timestamp fields."""

    created_at: datetime
    updated_at: datetime | None = None


class BaseResponse(BaseModel):
    """Standard API response."""

    success: bool = True
    message: str | None = None


class ErrorResponse(BaseModel):
    """Standard error response."""

    success: bool = False
    error: str
    detail: str | None = None
    code: str | None = None


class HealthResponse(BaseModel):
    """What a client can learn about this deployment's limits before uploading.

    Two upload ceilings, because there are two: a knowledge-base document is
    chunked and embedded, a chat attachment may be pasted whole into a prompt,
    and they are configured separately (#498). A client that reads only the
    first will refuse a file the chat surface would have taken, or accept one it
    will not.
    """

    status: str
    max_upload_size_mb: int | None = None
    chat_max_upload_size_mb: int | None = None


class HealthDetailResponse(BaseModel):
    status: str
    timestamp: str
    service: str
    checks: dict[str, Any] | None = None
    details: dict[str, Any] | None = None
