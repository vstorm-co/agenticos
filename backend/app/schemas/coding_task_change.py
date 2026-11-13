"""What one coding-agent task changed in its sandbox (#2480)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import BaseSchema, TimestampSchema

ChangeStatus = Literal["added", "modified", "deleted", "renamed"]

MAX_REVERT_FILE_BYTES = 2 * 1024 * 1024
MAX_REVERT_BYTES = 16 * 1024 * 1024


class ChangedFile(BaseSchema):
    """One file a task added, changed, removed or renamed, with its part of the patch.

    `patch` is the file's section of a unified diff - its `diff --git` header and
    its hunks - and `None` once the task's patch had run past its ceiling before
    this file. `truncated` marks the one file whose section was cut part way. A
    binary file carries Git's binary patch instead of text hunks. Blob ids and
    modes record the full before/after states; older display-only rows omit them.
    """

    # A patch is text whose leading and trailing whitespace is content.
    model_config = ConfigDict(str_strip_whitespace=False)

    path: str
    old_path: str | None = None
    status: ChangeStatus
    additions: int = 0
    deletions: int = 0
    binary: bool = False
    patch: str | None = None
    truncated: bool = False
    before_blob: str | None = None
    after_blob: str | None = None
    before_mode: str | None = None
    after_mode: str | None = None


class ChangeSet(BaseSchema):
    """Every file a task changed, in the order git lists them.

    `omitted` counts the changed files past the ceiling on how many are kept,
    which have no entry at all; `truncated` is set when anything - a file, or a
    part of the patch - was left out.
    """

    files: list[ChangedFile] = []
    omitted: int = 0
    truncated: bool = False
    # Raw bytes survive non-UTF-8 files. Only the display patch reaches the API.
    revert_patch: str | None = Field(default=None, exclude=True)


class CodingTaskChangeRead(ChangeSet, TimestampSchema):
    """A task's change set, as the console reads it under the task's panel."""

    id: UUID
    conversation_id: UUID
    harness: str
    can_revert: bool = False
    reverted_at: datetime | None = None
    revert_status: Literal["pending", "unknown", "failed"] | None = None
    revert_conflicting_files: list[str] = []
