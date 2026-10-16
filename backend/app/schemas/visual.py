"""Saving a visual from the conversation as an app."""

from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class VisualPublish(BaseSchema):
    """The app a visual is saved as. The same name again adds a version to that app."""

    name: str = Field(
        min_length=1,
        max_length=64,
        description="The app's handle: lower-case letters, digits and hyphens",
    )
    title: str | None = Field(
        default=None,
        max_length=200,
        description="What the app is called; the visual's title when omitted",
    )


class VisualPublished(BaseSchema):
    """The app version a visual became."""

    artifact_id: UUID
    version: int
    name: str
    title: str
    created: bool
    unchanged: bool
    url: str = Field(description="Where the app opens in the console")
