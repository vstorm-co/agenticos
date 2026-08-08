"""Schemas for file upload operations."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class FileUploadResponse(BaseSchema):
    """Response after successful file upload."""

    id: UUID
    filename: str
    mime_type: str
    size: int
    file_type: str
    preview: str | None = Field(
        default=None,
        description=(
            "First few lines of the extracted text, for a client to show beside the "
            "filename. Null for an image, and for a file no parser could read."
        ),
    )


class FileInfo(FileUploadResponse):
    """Full file metadata."""

    created_at: datetime
    user_id: UUID
