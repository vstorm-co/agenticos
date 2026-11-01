"""A folder on a person's own computer that a run works in (#2305).

A schema rather than a hub type because a chat frame and a stored trigger both
carry it; the device hub's workspace is what acts on it.
"""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

LocalMode = Literal["read_only", "workspace_write", "full_access"]


class LocalTarget(BaseModel):
    """Where a run works: a folder on one of the person's computers."""

    folder: str | None = Field(default=None, min_length=1, max_length=1024)
    """The folder the person picked in the app; the app refuses any it did not grant."""

    mode: LocalMode = "workspace_write"
    """How far the run may reach: read only, write in the folder, or full access."""

    computer_grant: UUID | None = None
    """Native whole-computer consent, bound by the app to this conversation."""

    device_id: UUID | None = None
    """Which computer, when the person has several; empty takes the one most recently connected."""

    model_service: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_]{1,48}$")] | None = None
    """An approved model service on this computer; no cloud fallback."""

    mcp_services: list[Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_]{1,48}$")]] = Field(
        default_factory=list, max_length=8
    )
    """Approved HTTP MCP services to add for this run, explicitly chosen by its owner."""

    computer: bool = False
    """Use this person's screen and input, independently of files and the agent spec."""

    browser: bool = False
    """Override the agent browser with this computer, independently of its sandbox."""

    skills: list[Literal["agents", "claude", "codex"]] = Field(default_factory=list, max_length=3)
    """Which of this computer's skill folders (`~/.agents`, `~/.claude`, `~/.codex`) the run may
    read, in place, together with the `AGENTS.md` files; empty uses none of them."""

    @model_validator(mode="after")
    def require_work_or_browser(self) -> Self:
        if self.computer_grant is not None and (self.folder is None or self.mode != "full_access"):
            raise ValueError("Whole-computer access requires its home folder and full access")
        if self.folder is None and (
            not (self.browser or self.computer or self.skills)
            or self.model_service is not None
            or self.mcp_services
        ):
            raise ValueError(
                "Choose a folder for local work, or select only local browser, computer use or skills"
            )
        return self
