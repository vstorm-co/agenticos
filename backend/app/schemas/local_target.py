"""A folder on a person's own computer that a run works in (#2305).

A schema rather than a hub type because a chat frame and a stored trigger both
carry it; the device hub's workspace is what acts on it.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

LocalMode = Literal["read_only", "workspace_write", "full_access"]


class LocalTarget(BaseModel):
    """Where a run works: a folder on one of the person's computers."""

    folder: str = Field(min_length=1, max_length=1024)
    """The folder the person picked in the app; the app refuses any it did not grant."""

    mode: LocalMode = "workspace_write"
    """How far the run may reach: read only, write in the folder, or full access."""

    device_id: UUID | None = None
    """Which computer, when the person has several; empty takes the one most recently connected."""

    model_service: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_]{1,48}$")] | None = None
    """An approved model service on this computer; no cloud fallback."""

    mcp_services: list[Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_]{1,48}$")]] = Field(
        default_factory=list, max_length=8
    )
    """Approved HTTP MCP services to add for this run, explicitly chosen by its owner."""

    browser: bool = False
    """Use an approved, separate Chromium window on this computer for browser tools."""
