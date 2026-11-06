"""A folder on a person's own computer that a run works in (#2305).

A schema rather than a hub type because a chat frame and a stored trigger both
carry it; the device hub's workspace is what acts on it.
"""

import hashlib
import json
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

LocalMode = Literal["read_only", "workspace_write", "full_access"]


class LocalOperations(BaseModel):
    """Shell execution can write in its folder, so it always requires write access."""

    model_config = ConfigDict(extra="forbid", strict=True)

    read: bool = True
    write: bool = False
    execute: bool = False

    @model_validator(mode="after")
    def require_read_and_shell_writes(self) -> Self:
        if not self.read or (self.execute and not self.write):
            raise ValueError(
                "Every folder grant requires read; executing commands also requires write"
            )
        return self


class RoutineLocalScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["routine"] = "routine"
    grant_id: UUID
    organization_id: UUID
    routine_id: UUID
    user_id: UUID
    device_id: UUID
    operations: LocalOperations


class LocalTarget(BaseModel):
    """Where a run works: a folder on one of the person's computers."""

    folder: str | None = Field(default=None, min_length=1, max_length=1024)
    """The folder the person picked in the app; the app refuses any it did not grant."""

    mode: LocalMode = "workspace_write"
    """How far the run may reach: read only, write in the folder, or full access."""

    computer_grant: UUID | None = None
    """Native whole-computer consent, bound by the app to this conversation or to this agent."""

    device_id: UUID | None = None
    """Which computer, when the person has several; empty takes the one most recently connected."""

    routine_grant: UUID | None = None
    """Native standing consent for this exact routine, folder, device and operations."""

    operations: LocalOperations | None = None
    """Explicit operation ceiling for a routine grant; interactive targets retain their modes."""

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

    coding_agent: Literal["claude_code", "codex"] | None = None
    """Use this local coding harness for this run, independently of the published binding."""

    coding_model: str | None = Field(default=None, pattern=r"^[^\x00-\x20\x7f]{1,256}$")
    """The local harness's model identifier; unset retains its own settings."""

    coding_effort: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    """The reasoning level advertised by the local harness, applied before its prompt."""

    skills: list[Literal["agents", "claude", "codex"]] = Field(default_factory=list, max_length=3)
    """Which of this computer's skill folders (`~/.agents`, `~/.claude`, `~/.codex`) the run may
    read, in place, together with the `AGENTS.md` files; empty uses none of them."""

    @model_validator(mode="after")
    def require_work_or_browser(self) -> Self:
        if self.routine_grant is not None:
            if (
                self.device_id is None
                or self.folder is None
                or self.operations is None
                or self.computer_grant is not None
                or self.computer
                or self.browser
                or self.model_service is not None
                or self.mcp_services
                or self.mode != ("workspace_write" if self.operations.write else "read_only")
            ):
                raise ValueError(
                    "Routine consent requires a specific device, folder and matching operation mode; local browser, screen, services and full access need separate authority"
                )
        elif self.operations is not None:
            raise ValueError("Routine operations require native routine consent")

        if self.coding_agent is None and (
            self.coding_model is not None or self.coding_effort is not None
        ):
            raise ValueError(
                "Choose a local coding agent before changing its model or reasoning level"
            )
        if self.coding_agent is not None and (self.folder is None or self.mode != "full_access"):
            raise ValueError(
                "Choose a folder with full access, or the whole computer, to use a local coding agent"
            )
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

    def routine_scope(
        self, *, organization_id: UUID, routine_id: UUID, user_id: UUID
    ) -> RoutineLocalScope:
        """Build only trusted server context; a general folder grant never supplies this."""
        if self.routine_grant is None or self.device_id is None or self.operations is None:
            raise ValueError(
                "Review this routine's device, folder and operations on the desktop app"
            )
        return RoutineLocalScope(
            grant_id=self.routine_grant,
            organization_id=organization_id,
            routine_id=routine_id,
            user_id=user_id,
            device_id=self.device_id,
            operations=self.operations,
        )

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()


def target_fingerprint(value: object) -> str | None:
    return None if value is None else LocalTarget.model_validate(value).fingerprint()
