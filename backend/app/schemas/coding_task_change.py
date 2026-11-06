"""What one coding-agent task changed in its sandbox (#2480)."""

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict

from app.schemas.base import BaseSchema, TimestampSchema

ChangeStatus = Literal["added", "modified", "deleted", "renamed"]


class ChangedFile(BaseSchema):
    """One file a task added, changed, removed or renamed, with its part of the patch.

    `patch` is the file's section of a unified diff - its `diff --git` header and
    its hunks - and `None` once the task's patch had run past its ceiling before
    this file. `truncated` marks the one file whose section was cut part way. A
    binary file has a header and no hunks.
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


class ChangeSet(BaseSchema):
    """Every file a task changed, in the order git lists them.

    `omitted` counts the changed files past the ceiling on how many are kept,
    which have no entry at all; `truncated` is set when anything - a file, or a
    part of the patch - was left out.
    """

    files: list[ChangedFile] = []
    omitted: int = 0
    truncated: bool = False


class CodingTaskChangeRead(ChangeSet, TimestampSchema):
    """A task's change set, as the console reads it under the task's panel."""

    id: UUID
    conversation_id: UUID
    harness: str
