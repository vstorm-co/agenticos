"""Targeted detail tools keep source identity, access paths and revision boundaries."""

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastmcp.exceptions import ToolError
from pydantic import JsonValue

from app.services.platform_mcp._details import detail_operations

pytestmark = pytest.mark.anyio
ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER = UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture
def api() -> MagicMock:
    value = MagicMock()
    value.request = AsyncMock()
    return value


def functions(api: MagicMock) -> dict[str, Callable[..., Awaitable[object]]]:
    return {name: function for name, function, _ in detail_operations(api)}


@pytest.mark.parametrize("contract", ["solution", "agent", "workflow", "workflow_preparation"])
async def test_contract_discovery_is_on_demand_and_can_read_selected_schema_fields(
    api: MagicMock, contract: str
) -> None:
    tool = functions(api)["get_authoring_schema"]
    result = await tool(contract)
    assert result["total"] > 0
    assert len(result["items"]) <= 10
    selected = await tool(contract, pointer="/type", mode="content")
    assert selected["content"] == "object"
    api.request.assert_not_awaited()


@pytest.mark.parametrize(
    "name,arguments,path",
    [
        ("read_context_file_content", {"context_id": ID}, f"/context/{ID}"),
        ("read_skill_content", {"skill_id": ID}, f"/skills/{ID}"),
        (
            "get_skill_resource",
            {"skill_id": ID, "resource_id": OTHER},
            f"/skills/{ID}/resources/{OTHER}",
        ),
    ],
)
async def test_large_text_is_windowed_at_its_existing_authorized_route(
    api: MagicMock, name: str, arguments: dict[str, UUID], path: str
) -> None:
    api.request.return_value = {"content": "x" * 100000}
    result = await functions(api)[name](**arguments, chars=10)
    assert result["content"] == "x" * 10
    assert result["next_offset"] == 10
    api.request.assert_awaited_once_with("GET", path, params=None)


async def test_skill_discovery_separates_uses_forks_and_reference_files(api: MagicMock) -> None:
    tools = functions(api)
    usage: JsonValue = {
        "agent": {"id": str(ID), "name": "Support"},
        "binding": {"state": "main"},
        "draft_only": False,
        "checked_versions": ["large evidence"],
    }
    api.request.return_value = {"items": [usage], "hidden": 2}
    result = await tools["list_skill_agents"](ID)
    assert result["items"] == [
        {"agent_id": str(ID), "name": "Support", "draft_only": False, "state": "main"}
    ]
    assert result["hidden"] == 2
    assert (await tools["list_skill_agents"](ID, detailed=True))["items"] == [usage]
    api.request.return_value = {"items": [{"id": str(ID), "content": "full"}]}
    assert (await tools["list_skill_forks"](ID))["items"] == [{"id": str(ID)}]
    assert (await tools["list_skill_forks"](ID, detailed=True))["items"][0]["content"] == "full"
    api.request.return_value = {
        "resources": [{"id": str(ID), "name": "policy.md"}, {"id": str(OTHER), "name": "guide.md"}]
    }
    assert (await tools["list_skill_resources"](ID, q="policy"))["items"][0]["id"] == str(ID)
    api.request.return_value = {}
    assert (await tools["list_skill_resources"](ID))["items"] == []


@pytest.mark.parametrize("version", [None, 3])
async def test_case_reads_pin_the_requested_dataset_version(
    api: MagicMock, version: int | None
) -> None:
    tools = functions(api)
    api.request.return_value = {
        "case_id": str(OTHER),
        "input": "question",
        "history": [{"role": "user", "content": "source"}],
    }
    result = await tools["get_dataset_case"](ID, OTHER, version)
    assert result["case_id"] == str(OTHER)
    assert api.request.call_args.kwargs["params"] == (None if version is None else {"version": 3})
    body = await tools["read_dataset_case_field"](ID, OTHER, "input", version=version, chars=3)
    assert body["content"] == "que"
    history = await tools["read_dataset_case_field"](ID, OTHER, "history", version=version)
    assert history["encoding"] == "json-fragment"


@pytest.mark.parametrize(
    "name,path,argument",
    [
        ("get_model_profile", "/providers/model-profiles", ID),
        ("get_model_provider", "/providers/catalog", "anthropic"),
    ],
)
async def test_profile_and_provider_details_select_only_an_authorized_identity(
    api: MagicMock, name: str, path: str, argument: UUID | str
) -> None:
    api.request.return_value = {"items": [{"id": str(argument), "label": "Selected"}]}
    assert (await functions(api)[name](argument))["label"] == "Selected"
    api.request.assert_awaited_once_with("GET", path, params=None)
    api.request.return_value = {"items": [{"id": str(OTHER)}]}
    with pytest.raises(ToolError, match="not found"):
        await functions(api)[name](argument)


async def test_connector_schema_is_loaded_for_one_source_type(api: MagicMock) -> None:
    api.request.return_value = {"items": [{"type": "github", "config_schema": {"type": "object"}}]}
    result = await functions(api)["get_knowledge_connector"](ID, "github")
    assert result["config_schema"] == {"type": "object"}
    with pytest.raises(ToolError, match="not found"):
        await functions(api)["get_knowledge_connector"](ID, "missing")


async def test_draft_nodes_can_be_found_without_loading_configurations(api: MagicMock) -> None:
    api.request.return_value = {
        "draft_revision": 7,
        "draft_graph": {
            "nodes": [
                {
                    "id": str(ID),
                    "definition_id": "http.request",
                    "config": {"url": "https://example.com"},
                }
            ]
        },
    }
    tools = functions(api)
    result = await tools["list_workflow_definition_nodes"](OTHER, q="http")
    assert result["draft_revision"] == 7
    assert "config" not in result["items"][0]
    node = await tools["get_workflow_definition_node"](OTHER, ID)
    assert node["draft_revision"] == 7 and node["node"]["config"]["url"] == "https://example.com"
    with pytest.raises(ToolError, match="not found"):
        await tools["get_workflow_definition_node"](OTHER, OTHER)
    api.request.return_value = {"draft_revision": 0, "draft_graph": None}
    assert (await tools["list_workflow_definition_nodes"](OTHER))["items"] == []


async def test_step_detail_filters_in_the_api_instead_of_scanning_every_output(
    api: MagicMock,
) -> None:
    api.request.return_value = {
        "items": [{"id": str(OTHER), "status": "completed", "output": {"text": "x" * 100000}}]
    }
    tools = functions(api)
    result = await tools["get_workflow_execution_step"](
        ID, OTHER, pointer="/output", mode="content"
    )
    assert result["encoding"] == "json-fragment" and result["next_offset"] == 2000
    api.request.assert_awaited_once_with(
        "GET",
        f"/workflow-runs/{ID}/nodes",
        params={"node_run_id": str(OTHER), "limit": 1, "skip": 0},
    )
    api.request.return_value = {"items": [{"id": str(ID)}]}
    with pytest.raises(ToolError, match="not found"):
        await tools["get_workflow_execution_step"](ID, OTHER)


@pytest.mark.parametrize(
    "name,args,path",
    [
        ("get_embedding_endpoint", (OTHER,), "/local-services"),
        ("get_agent_environment", (ID, OTHER), f"/agents/{ID}/environments"),
        ("get_eval_suite", (ID, OTHER), f"/agents/{ID}/eval-suites"),
        ("get_knowledge_source", (ID, OTHER), f"/kb/{ID}/sync-sources"),
        ("get_routine", (ID, OTHER), f"/agents/{ID}/triggers"),
        ("get_watch", (OTHER,), "/me/watches"),
    ],
)
async def test_selected_configuration_is_fetched_without_expanding_its_discovery_page(
    api: MagicMock, name: str, args: tuple[UUID, ...], path: str
) -> None:
    api.request.return_value = {"items": [{"id": str(OTHER), "config": {"setting": "value"}}]}
    result = await functions(api)[name](*args)
    assert result["config"] == {"setting": "value"}
    api.request.assert_awaited_once_with("GET", path, params=None)
