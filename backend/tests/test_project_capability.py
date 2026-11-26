"""Project tools keep author control and delegate only through the admitted port."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic_ai.workspaces import WorkspaceUnavailableError

from app.agents.capabilities import CapabilityBinding, build, get, load_builtins
from app.agents.capabilities.projects._capability import build_projects
from app.agents.capabilities.projects._toolset import PROJECT_CONTEXT_RESOURCE, project_tools
from app.core.exceptions import AuthorizationError, BadRequestError

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def port() -> SimpleNamespace:
    return SimpleNamespace(
        search=AsyncMock(return_value="matches"),
        select=AsyncMock(return_value="selected"),
        files=AsyncMock(return_value="files"),
        read_file=AsyncMock(return_value="text"),
        write_file=AsyncMock(return_value="saved"),
        transfer_file=AsyncMock(return_value="receipt"),
    )


@pytest.mark.parametrize(
    "name,args,method",
    [
        ("search_projects", ("XYZ", 3), "search"),
        ("select_project_context", (uuid4(),), "select"),
        ("list_project_files", ("notes",), "files"),
        ("read_project_file", ("notes/a.md",), "read_file"),
        ("write_project_file", ("notes/a.md", "agreed"), "write_file"),
        ("transfer_project_file", ("to_agent", "input.bin", "input.bin", None), "transfer_file"),
    ],
)
async def test_tools_keep_the_admitted_port_and_sequential_barrier(
    port: SimpleNamespace, name: str, args: tuple[str | int | UUID, ...], method: str
) -> None:
    tool = project_tools(port).tools[name]
    assert tool.sequential
    answer = await tool.function(*args)
    call = getattr(port, method)
    assert answer == call.return_value
    call.assert_awaited_once_with(*args)


async def test_no_port_is_an_explicit_refusal_and_no_external_work() -> None:
    assert "unavailable" in await project_tools(None).tools["select_project_context"].function()
    assert build_projects(None) is not None


@pytest.mark.parametrize(
    "error,message",
    [
        (AuthorizationError(message="Access revoked"), "Access revoked"),
        (PermissionError("Denied"), "Denied"),
        (WorkspaceUnavailableError("Not retained"), "Not retained"),
        (FileNotFoundError("private provider path"), "project path is missing"),
        (IsADirectoryError("private provider path"), "project path is missing"),
        (NotADirectoryError("private provider path"), "project path is missing"),
    ],
)
async def test_refusals_do_not_ask_the_model_to_retry_or_leak_missing_provider_paths(
    port: SimpleNamespace, error: Exception, message: str
) -> None:
    port.read_file.side_effect = error
    answer = await project_tools(port).tools["read_project_file"].function("notes.txt")
    assert message in answer
    assert "private provider path" not in answer


def test_registry_declares_every_tool_and_write_policy_and_requires_scopes(
    port: SimpleNamespace,
) -> None:
    load_builtins()
    definition = get("projects")
    assert definition is not None
    assert {tool.id for tool in definition.tools} == set(project_tools(port).tools)
    assert {tool.id for tool in definition.tools if tool.side_effecting} == {
        "write_project_file",
        "transfer_project_file",
    }
    with pytest.raises(BadRequestError):
        build(
            [CapabilityBinding(capability_id="projects")],
            granted_scopes=frozenset({"projects:read"}),
        )
    assert build(
        [CapabilityBinding(capability_id="projects")],
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        resources={PROJECT_CONTEXT_RESOURCE: port},
    )
    assert build(
        [CapabilityBinding(capability_id="projects")],
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        resources={},
    )
