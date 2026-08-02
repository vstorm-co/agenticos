"""What a person is shown about the files an agent kept."""

from __future__ import annotations

from pydantic import Field

from app.schemas.base import BaseSchema


class WorkspaceFileRead(BaseSchema):
    """One file in a workspace, as a listing shows it."""

    path: str
    size: int | None = Field(default=None, description="Bytes, or null for a directory entry")
    is_dir: bool = False


class WorkspaceListing(BaseSchema):
    """A workspace and whose it is.

    `owner_label` exists because "this conversation's files" is wrong for three
    of the four scopes, and wrong in the direction that alarms people: under
    `agent` scope a user opens a chat and sees a file they never created. The
    label is what turns that from an apparent leak into an explanation.
    """

    scope: str
    backend: str
    owner_label: str = Field(description="Whose workspace this is, in words a person can read")
    items: list[WorkspaceFileRead]
    total: int
    bytes_total: int = 0


class WorkspaceFileContent(BaseSchema):
    """One file's contents, for a person reading it rather than an agent.

    Text only. A workspace can hold a PNG an agent produced, and serving it here
    would mean this endpoint deciding content types, sniffing bytes and setting
    disposition headers - a download path, which is its own change with its own
    threat model. Until then a binary file is listed and reported as binary
    rather than half-served.
    """

    path: str
    content: str
    truncated: bool = False
