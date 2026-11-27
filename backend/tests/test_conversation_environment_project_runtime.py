"""Both initial GUI startup and later observers receive the same owned path."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.workspaces import CommandResult, WorkspaceRef

from app.agents.capabilities.computer_use._actions import TypeText
from app.db import session as sessions
from app.db.models.project import Project
from app.schemas.project_filesystem_authority import ProjectFilesystemLeaseRead
from app.services import conversation_environment_project_files as files
from app.services import conversation_environment_runtime as runtime
from app.services.project_filesystem_bindings import ProjectFilesystemBindingService
from tests.test_conversation_environment_runtime import case as case

pytestmark = pytest.mark.anyio


async def test_gui_start_receives_stable_environment_path_before_ready(case, monkeypatch):
    lease_id, binding_id, project_id = uuid4(), uuid4(), uuid4()
    opened = replace(case.opened, filesystem_binding_id=binding_id)
    monkeypatch.setattr(
        runtime.SandboxWorkspaceService, "open_for_environment", AsyncMock(return_value=opened)
    )
    configured = replace(
        case.desktop, authority=replace(case.desktop.authority, project=Project(id=project_id))
    )
    issued = ProjectFilesystemLeaseRead(
        id=lease_id,
        project_id=project_id,
        workspace_generation=None,
        path=f"/project/{lease_id}",
        expires_at=datetime.now(UTC),
    )
    issue = AsyncMock(return_value=issued)
    monkeypatch.setattr(ProjectFilesystemBindingService, "issue_environment_lease", issue)
    events = []

    @asynccontextmanager
    async def session():
        yield case.db
        events.append("committed lease")

    monkeypatch.setattr(sessions, "get_worker_db_context", session)

    async def store(resource, key):
        events.append(("journal", resource.project_lease_id))
        return True

    async def start(workspace, **dimensions):
        events.append("GUI startup")
        assert isinstance(workspace, files.ProjectDesktopWorkspace)
        assert workspace.project_directory == f"/project/{lease_id}"

    monkeypatch.setattr(runtime, "open_sandbox_desktop", AsyncMock(side_effect=start))
    await runtime.provision(configured, case.payload, store, case.drive)
    issue.assert_awaited_once()
    assert issue.await_args.kwargs["binding_id"] == binding_id
    assert (
        events.index("committed lease")
        < events.index(("journal", lease_id))
        < events.index("GUI startup")
    )


async def test_later_desktop_observer_keeps_the_same_gui_project_path(case):
    lease_id = uuid4()
    resource = case.resource.model_copy(update={"project_lease_id": lease_id})
    async with runtime.open_view(resource, case.desktop) as view:
        assert isinstance(view, runtime.DesktopEnvironmentView)
        case.workspace.run = AsyncMock(
            return_value=CommandResult(exit_code=0, stdout="", stderr="")
        )
        await view.computer.perform(TypeText(text="a retained editor value"))
        assert case.workspace.run.await_args.kwargs["env"]["PROJECT_DIR"] == f"/project/{lease_id}"


class LegacyDesktopResource(BaseModel):
    """The sealed desktop contract before environment Project mounts shipped."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["desktop"] = "desktop"
    environment_id: UUID
    organization_id: UUID
    backend: Literal["sandbox", "daemon", "e2b"]
    workspace_id: UUID | None = None
    workspace_ref: WorkspaceRef | None = None
    connection_id: UUID | None = None
    connection_fingerprint: str | None = None
    workspace_root: str | None = None
    credential: str = Field(default="", repr=False)
    daemon_url: str = Field(default="", repr=False)
    width: int = Field(ge=640, le=1920)
    height: int = Field(ge=480, le=1200)


def test_unmounted_desktop_serialization_still_loads_the_legacy_sealed_contract(case):
    resource = case.resource.model_copy(update={"workspace_ref": None})
    restored = LegacyDesktopResource.model_validate_json(resource.model_dump_json())
    assert restored.model_dump() == resource.model_dump()
    assert "workspace_ref" in resource.model_dump()
    assert "project_lease_id" not in resource.model_dump()


def test_mounted_desktop_has_explicit_new_contract_requiring_drain_before_rollback(case):
    resource = case.resource.model_copy(update={"project_lease_id": uuid4()})
    with pytest.raises(ValidationError, match="project_lease_id"):
        LegacyDesktopResource.model_validate_json(resource.model_dump_json())
