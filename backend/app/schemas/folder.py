"""Folder schemas (#2124)."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.db.models.resource_grant import Visibility
from app.schemas.base import BaseSchema
from app.schemas.resource_grant import AudienceChoice


class FolderCreate(AudienceChoice):
    """A new folder: its name, where it goes, and who it reaches.

    The audience defaults to the whole organization, like a new resource's, and
    is narrowed to fit inside the parent's - asking for more than the parent
    reaches is refused rather than quietly trimmed.
    """

    name: str = Field(min_length=1, max_length=120)
    parent_id: UUID | None = Field(
        default=None, description="The folder it goes in; none puts it at the top level."
    )


class FolderUpdate(BaseSchema):
    """A rename, a move to another parent, or both."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: UUID | None = Field(
        default=None,
        description="Move it under this folder. Set `to_top` to move it to the top level.",
    )
    to_top: bool = Field(default=False, description="Move it to the top level.")


class FolderRead(BaseSchema):
    """One folder as a reader sees it."""

    id: UUID
    kind: str
    parent_id: UUID | None
    name: str
    owner_user_id: UUID | None
    visibility: Visibility
    group_ids: list[UUID] = Field(
        default_factory=list, description="The groups its audience names, when it is narrowed."
    )
    user_ids: list[UUID] = Field(
        default_factory=list, description="The people its audience names, when it is narrowed."
    )
    item_count: int = Field(default=0, description="Resources filed directly in it.")
    can_edit: bool = Field(
        description="Whether the reader may rename, move, re-audience or delete it."
    )
    created_at: datetime
    updated_at: datetime | None = None


class FolderList(BaseSchema):
    items: list[FolderRead]
    total: int


class FileInFolder(BaseSchema):
    """Where a resource goes: a folder, or the top level."""

    folder_id: UUID | None = Field(
        default=None, description="The folder to file it in; none moves it to the top level."
    )
