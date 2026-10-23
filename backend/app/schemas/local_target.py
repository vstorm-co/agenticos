"""A folder on a person's own computer that a run works in (#2305).

A schema rather than a hub type because a chat frame and a stored trigger both
carry it; the device hub's workspace is what acts on it.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

LocalMode = Literal["read_only", "workspace_write", "full_access"]


class LocalTarget(BaseModel):
    """Where a run works: a folder on one of the person's computers."""

    folder: str = Field(min_length=1, max_length=1024)
    """The folder the person picked in the app; the app refuses any it did not grant."""

    mode: LocalMode = "workspace_write"
    """How far the run may reach: read only, write in the folder, or full access."""

    device_id: UUID | None = None
    """Which computer, when the person has several; empty takes the one most recently connected."""
