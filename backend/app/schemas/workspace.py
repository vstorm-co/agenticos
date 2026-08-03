"""What a person is shown about the files an agent kept."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

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


class WorkspaceSummary(BaseSchema):
    """One workspace in the organization-wide listing.

    No files. A deployment can hold a workspace per warm conversation, and
    reading each one to render a table would mean a query or a round trip per row
    for a page nobody has asked a question of yet - the files come when somebody
    opens one.
    """

    id: UUID
    agent_id: UUID
    agent_name: str = Field(description="Resolved server-side, so a row names something readable")
    conversation_id: UUID | None = None
    scope: str
    backend: str
    owner_label: str
    bytes_total: int = 0
    version: int = 0
    last_used_at: datetime | None = None
    created_at: datetime | None = None


class WorkspaceSummaryList(BaseSchema):
    items: list[WorkspaceSummary]
    total: int


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
