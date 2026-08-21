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
    modified_at: datetime | None = Field(
        default=None,
        description=(
            "When the file last changed, where the backend records one. A stored "
            "workspace records it on every write; a live container's shell listing "
            "does not, and null is the honest answer there - never 'just now'."
        ),
    )


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
    bytes_limit: int | None = Field(
        default=None,
        description=(
            "What this workspace fills up against, when this platform is what holds the "
            "ceiling. A stored workspace runs out against a deployment-wide cap and "
            "starts refusing writes, so a client can warn before that happens. Null for "
            "a container: its ceiling belongs to its host and is only knowable by "
            "sampling the session, which a listing does not pay for."
        ),
    )
    unreadable_reason: str | None = Field(
        default=None,
        description=(
            "Why this listing may be shorter than the workspace, or empty. A service "
            "started with no `workspace_root` keeps nothing on disk, so its files "
            "exist only while a sandbox runs and cannot be read without starting "
            "one; a host that is down will be up later. Neither is an error to raise "
            "- an empty list on its own reads as 'there are no files'."
        ),
    )


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
    agent_has_avatar: bool = Field(
        default=False,
        description=(
            "Whether the agent has a face to draw. Resolved here because the reader "
            "may not hold agents:view to ask the agent list."
        ),
    )
    conversation_id: UUID | None = None
    conversation_is_mine: bool = Field(
        default=False,
        description=(
            "Whether the linked conversation belongs to the caller. The chat page "
            "lists its owner's threads, so a link is only offered to the owner."
        ),
    )
    conversation_title: str | None = Field(
        default=None,
        description=(
            "The chat these files belong to, named rather than left as an id. Null "
            "for a workspace no single conversation owns."
        ),
    )
    conversations: int = Field(
        default=0,
        description=(
            "How many conversations reach these files. One for a conversation-scoped "
            "workspace, every chat with the agent for an agent-scoped one, and zero "
            "for a run-scoped one, which is gone before anybody could look."
        ),
    )
    scope: str
    backend: str
    owner_label: str
    access_label: str = Field(
        default="",
        description=(
            "Who can see these files, in words. `scope` is the mechanism; this is "
            "the consequence, and 'agent' does not tell a reader whether the file "
            "in front of them is one person's or the whole team's."
        ),
    )
    bytes_total: int = 0
    file_count: int | None = Field(
        default=None,
        description=(
            "How many files this workspace holds. Free for a stored one - the files "
            "are a column of the row - and null for a container until somebody asks "
            "for it, because counting those means a round trip to the host per "
            "workspace. `?measure=true` fills them in."
        ),
    )
    measured_bytes: int | None = Field(
        default=None,
        description=(
            "What the files come to, summed from the listing. Separate from "
            "`bytes_total`, which is the *stored document's* size and zero for a "
            "container: one field meaning two things depending on the backend is "
            "how a size column ends up claiming a container is empty."
        ),
    )
    version: int = 0
    last_used_at: datetime | None = None
    created_at: datetime | None = None


class WorkspaceSummaryList(BaseSchema):
    items: list[WorkspaceSummary]
    total: int
    measured: int = Field(
        default=0,
        description="How many workspaces were read to count their files.",
    )
    unreadable: int = Field(
        default=0,
        description=(
            "Workspaces whose host would not answer. Counted rather than dropped, so "
            "a shorter list does not read as fewer files."
        ),
    )
    truncated: bool = Field(
        default=False,
        description=(
            "Whether measuring stopped short of the list. Reading a container is a "
            "round trip, so the count is bounded and says so."
        ),
    )


class FlatFileRead(WorkspaceFileRead):
    """One file, with the workspace it came from named beside it.

    The flat view's row. A path on its own is ambiguous across workspaces -
    `/report.csv` exists in several - so the agent and who can see it travel with
    every entry rather than being implied by a heading somebody has scrolled past.
    """

    workspace_id: UUID
    agent_name: str
    access_label: str
    from_upload: bool = Field(
        default=False,
        description=(
            "Whether a person attached this file rather than an agent writing it. "
            "Read off the path: attachments land in `uploads/`, which is this "
            "application's own convention and the only signal there is - a host "
            "records no author. So it is a fact about where the file is, stated as "
            "what that means."
        ),
    )
    preview: str | None = Field(
        default=None,
        description=(
            "The first lines of a stored text file, so a tile can hint at its "
            "content. Null for binary content and for container-backed workspaces, "
            "whose bytes live on a host the flat listing does not visit per file."
        ),
    )
    thumbnail: str | None = Field(
        default=None,
        description=(
            "A stored image scaled down to a `data:` URI, so a tile draws the "
            "picture rather than a glyph. A URI rather than an address because the "
            "bytes are already in this listing's hand - an address would be a "
            "request per tile. Null for everything that is not a small stored image."
        ),
    )


class FlatFileList(BaseSchema):
    """Every file the caller can see, across their workspaces.

    `truncated` and `unreadable` are part of the answer, not diagnostics. A shorter
    list is indistinguishable from fewer files, and "no agent is holding that
    document" is a different statement from "we stopped looking" or "one host did
    not answer".
    """

    items: list[FlatFileRead]
    total: int
    workspaces_read: int = 0
    unreadable: int = Field(
        default=0, description="Workspaces whose host or document could not be read"
    )
    truncated: bool = Field(
        default=False, description="Whether more workspaces exist than were read"
    )


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
