"""Only actual, matching Project tools may adopt a retained GUI directory."""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.models.project import Project
from app.services import conversation_environment_agent as adapter
from app.services import conversation_environment_project_files as files
from app.services.conversation_environment_policy import EnvironmentNotReady
from tests.test_conversation_environment_agent_coordinator import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def project_case(case, monkeypatch):
    case.owner.kind = "desktop"
    project = Project(id=uuid4(), workspace_generation=uuid4())
    admitted = replace(case.resolved.authority, project=project)
    monkeypatch.setattr(adapter, "authority", AsyncMock(return_value=admitted))
    case.owner.environment_id = case.row.id
    case.owner.acquire = AsyncMock(return_value=True)
    lookup = AsyncMock(return_value=f"/project/{uuid4()}")
    monkeypatch.setattr(files, "directory", lookup)
    return case, project, admitted, lookup


async def test_actual_project_operation_uses_ready_directory_under_original_binding(project_case):
    case, project, _, lookup = project_case
    binding_id = uuid4()
    result = await case.owner.project_directory(
        binding_id, project.id, project.workspace_generation
    )
    assert result == lookup.return_value
    lookup.assert_awaited_once()
    assert lookup.await_args.kwargs["binding_id"] == binding_id
    assert lookup.await_args.kwargs["environment_id"] == case.row.id
    assert lookup.await_args.kwargs["project_id"] == project.id
    case.owner.acquire.assert_awaited_once()


@pytest.mark.parametrize("changed", ["target", "missing_project", "project", "generation"])
async def test_changed_selection_refuses_before_provider_adoption(
    project_case, monkeypatch, changed
):
    case, project, admitted, lookup = project_case
    if changed == "target":
        admitted = replace(admitted, execution_target="project")
    elif changed == "missing_project":
        admitted = replace(admitted, project=None)
    elif changed == "project":
        admitted = replace(
            admitted, project=Project(id=uuid4(), workspace_generation=project.workspace_generation)
        )
    else:
        admitted = replace(admitted, project=Project(id=project.id, workspace_generation=uuid4()))
    monkeypatch.setattr(adapter, "authority", AsyncMock(return_value=admitted))
    with pytest.raises(EnvironmentNotReady, match="different Project selection"):
        await case.owner.project_directory(uuid4(), project.id, project.workspace_generation)
    case.owner.acquire.assert_not_awaited()
    lookup.assert_not_awaited()


@pytest.mark.parametrize("missing_id", [False, True])
async def test_unavailable_owned_target_never_returns_a_run_path(project_case, missing_id):
    case, project, _, lookup = project_case
    if missing_id:
        case.owner.environment_id = None
    else:
        case.owner.acquire.return_value = False
    with pytest.raises(EnvironmentNotReady, match="No retained desktop"):
        await case.owner.project_directory(uuid4(), project.id, project.workspace_generation)
    lookup.assert_not_awaited()


from tests.test_run_project_workspace import setup as setup


@pytest.mark.parametrize("mounted", [False, True])
async def test_explicit_project_file_tool_prepares_gui_only_for_a_mounted_executor(setup, mounted):
    selector = setup.selector
    selector.filesystem_binding_id = uuid4() if mounted else None
    prepare = AsyncMock(return_value=f"/project/{uuid4()}")
    selector.environment_project_directory = prepare
    await selector.select(setup.guard.return_value.id)
    await setup.project.write_text("source.txt", "same canonical file")
    result = await selector.read_file("source.txt")
    assert "same canonical file" in result
    if mounted:
        prepare.assert_awaited_once_with(
            selector.filesystem_binding_id, selector.project_id, selector.project_generation, None
        )
    else:
        prepare.assert_not_awaited()
