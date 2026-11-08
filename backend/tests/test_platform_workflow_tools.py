"""The Architect builds workflows and table state through the scoped public API."""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.schemas.virtual_table import ColumnInput, RecordQuery, RecordUpdate, SchemaUpdate
from app.services.platform_mcp import _tools
from app.services.platform_mcp._api import PlatformApi
from app.services.platform_mcp._tools import platform_tools
from app.workflows.contracts.input_schema import MAX_DISCOVERY_BYTES
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio
ID = UUID("00000000-0000-4000-8000-000000000001")
GRAPH = WorkflowGraph(
    entry_node_id=ID,
    nodes=[
        NodeInstance(
            id=ID,
            definition_id="trigger.manual",
            definition_version=1,
            layout=NodePosition(x=0, y=0),
        )
    ],
    edges=[],
    bindings=[],
)


@pytest.mark.parametrize(
    ("name", "arguments", "method", "path", "writes"),
    [
        ("list_workflow_definitions", {}, "GET", "/workflows", False),
        ("get_workflow_definition", {"workflow_id": ID}, "GET", f"/workflows/{ID}", False),
        (
            "get_workflow_input_schema",
            {"workflow_id": ID},
            "GET",
            f"/workflows/{ID}/input-schema",
            False,
        ),
        ("create_workflow_draft", {"name": "Lead intake"}, "POST", "/workflows", True),
        (
            "update_workflow_draft",
            {"workflow_id": ID, "graph": GRAPH, "expected_revision": 3},
            "PATCH",
            f"/workflows/{ID}/draft",
            True,
        ),
        (
            "test_workflow_draft",
            {"workflow_id": ID, "run_input": {"lead": "Ada"}},
            "POST",
            "/workflow-runs",
            True,
        ),
        ("get_workflow_execution", {"run_id": ID}, "GET", f"/workflow-runs/{ID}", False),
        (
            "get_workflow_execution_steps",
            {"run_id": ID},
            "GET",
            f"/workflow-runs/{ID}/nodes",
            False,
        ),
        (
            "publish_workflow",
            {"workflow_id": ID, "expected_revision": 3},
            "POST",
            f"/workflows/{ID}/publish",
            True,
        ),
        ("list_virtual_tables", {"q": "Leads"}, "GET", "/tables", False),
        ("get_virtual_table", {"table_id": ID}, "GET", f"/tables/{ID}", False),
        (
            "create_virtual_table",
            {"name": "Leads", "columns": [ColumnInput(label="Name", type="text")]},
            "POST",
            "/tables",
            True,
        ),
        (
            "update_virtual_table_schema",
            {"table_id": ID, "schema": SchemaUpdate(expected_version=1, columns=[])},
            "PUT",
            f"/tables/{ID}/schema",
            True,
        ),
        ("query_virtual_table", {"table_id": ID}, "POST", f"/tables/{ID}/records/query", False),
        (
            "add_virtual_table_record",
            {"table_id": ID, "values": {"name": "Ada"}},
            "POST",
            f"/tables/{ID}/records",
            True,
        ),
        (
            "update_virtual_table_record",
            {
                "table_id": ID,
                "record_id": ID,
                "update": RecordUpdate(expected_revision=2, values={}),
            },
            "PATCH",
            f"/tables/{ID}/records/{ID}",
            True,
        ),
    ],
)
async def test_builder_tools_use_the_public_api_and_gate_writes(
    name: str, arguments: dict[str, object], method: str, path: str, writes: bool
) -> None:
    api = MagicMock(spec=PlatformApi)
    api.request = AsyncMock(return_value={"ok": True})
    tool = {tool.name: tool for tool in platform_tools(api)}[name]
    assert tool.writes is writes
    assert not tool.ungated
    assert await tool.function(**arguments) == {"ok": True}
    assert api.request.await_args.args == (method, path)
    if name == "update_workflow_draft":
        assert api.request.await_args.kwargs["json"] == {
            "graph": GRAPH.model_dump(mode="json"),
            "expected_revision": 3,
        }
    if name == "test_workflow_draft":
        assert api.request.await_args.kwargs["json"] == {
            "workflow_id": str(ID),
            "mode": "test",
            "input": {"lead": "Ada"},
        }
    if name == "query_virtual_table":
        assert api.request.await_args.kwargs["json"] == RecordQuery().model_dump(mode="json")


async def test_listing_tables_without_a_search_sends_only_the_page() -> None:
    api = MagicMock(spec=PlatformApi)
    api.request = AsyncMock(return_value={"items": [], "total": 0})
    tool = {tool.name: tool for tool in platform_tools(api)}["list_virtual_tables"]

    await tool.function()

    assert api.request.await_args.kwargs["params"] == {"limit": 50, "skip": 0}


async def test_input_schema_discovery_can_select_a_published_version() -> None:
    api = MagicMock(spec=PlatformApi)
    api.request = AsyncMock(return_value={"entries": []})
    tool = {tool.name: tool for tool in platform_tools(api)}["get_workflow_input_schema"]
    await tool.function(workflow_id=ID, version_id=ID)
    assert api.request.await_args.kwargs["params"] == {"version_id": str(ID)}


async def test_publication_withholds_one_time_credentials() -> None:
    api = MagicMock(spec=PlatformApi)
    api.request = AsyncMock(
        return_value={
            "version": {"version": 1},
            "webhook_secret": "must-not-reach-the-model",
            "trigger_secrets": {"node": "also-private"},
        }
    )
    publish = {tool.name: tool for tool in platform_tools(api)}["publish_workflow"]
    assert await publish.function(workflow_id=ID, expected_revision=2) == {
        "version": {"version": 1}
    }
    assert api.request.await_args.kwargs["json"] == {"expected_revision": 2, "note": ""}


async def test_the_catalog_is_discovered_before_full_step_schemas_are_read() -> None:
    api = MagicMock(spec=PlatformApi)
    entry = {
        "id": "http.request",
        "version": 1,
        "name": "HTTP request",
        "description": "Call an API",
        "category": "network",
        "kind": "action",
        "ports": [],
        "effect_kind": "read",
        "retry_guarantee": "none",
    }
    api.request = AsyncMock(return_value={"items": [entry], "total": 1})
    tools = {tool.name: tool for tool in platform_tools(api)}
    brief = await tools["list_workflow_nodes"].function()
    assert brief["items"][0]["id"] == "http.request"
    assert "config_schema" not in brief["items"][0]
    full = await tools["get_workflow_node"].function(definition_id="http.request")
    assert full["id"] == "http.request" and "config_schema" in full
    api.refuse.return_value = {"error": "Missing"}
    assert await tools["get_workflow_node"].function(definition_id="made.up") == {
        "error": "Missing"
    }
    api.refuse.assert_called_once()


@pytest.mark.parametrize(
    ("count", "character", "length"),
    [(1, "x", MAX_DISCOVERY_BYTES), (1, "界", MAX_DISCOVERY_BYTES // 2), (50, "x", 1024)],
)
async def test_mcp_schema_discovery_refuses_oversized_results_instead_of_partial_contracts(
    count: int, character: str, length: int
) -> None:
    response = {
        "entries": [
            {"trigger": "core.input", "input_schema": {"description": character * length}}
            for _ in range(count)
        ]
    }
    api = MagicMock(spec=PlatformApi)
    api.request = AsyncMock(return_value=response)
    api.refuse.return_value = {"error": "bounded refusal"}
    tool = {tool.name: tool for tool in platform_tools(api)}["get_workflow_input_schema"]
    assert await tool.function(workflow_id=ID) == {"error": "bounded refusal"}
    api.refuse.assert_called_once()
    assert "32 KiB allowance" in api.refuse.call_args.args[0]
    assert "No partial contract" in api.refuse.call_args.args[0]


async def test_mcp_schema_discovery_preserves_the_exact_utf8_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {"entries": [{"trigger": "core.input", "input_schema": {"description": "界"}}]}
    size = len(json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode())
    api = MagicMock(spec=PlatformApi)
    api.request = AsyncMock(return_value=response)
    api.refuse.return_value = {"error": "bounded refusal"}
    tool = {tool.name: tool for tool in platform_tools(api)}["get_workflow_input_schema"]
    monkeypatch.setattr(_tools, "MAX_DISCOVERY_BYTES", size)
    assert await tool.function(workflow_id=ID) == response
    api.refuse.assert_not_called()
    monkeypatch.setattr(_tools, "MAX_DISCOVERY_BYTES", size - 1)
    assert await tool.function(workflow_id=ID) == {"error": "bounded refusal"}


async def test_mcp_schema_discovery_only_advertises_entries_its_run_tool_can_start() -> None:
    manual = {
        "trigger": "trigger.manual",
        "entry_node_id": str(ID),
        "input_schema": {"type": "object"},
    }
    api_entry = {**manual, "trigger": "core.input"}
    response = {
        "workflow_id": str(ID),
        "entries": [
            manual,
            {**manual, "trigger": "trigger.workflow_call"},
            {
                **manual,
                "trigger": "trigger.form",
                "input_schema": {"description": "x" * MAX_DISCOVERY_BYTES},
            },
            api_entry,
        ],
    }
    api = MagicMock(spec=PlatformApi)
    api.request = AsyncMock(return_value=response)
    tool = {tool.name: tool for tool in platform_tools(api)}["get_workflow_input_schema"]
    assert await tool.function(workflow_id=ID) == {
        "workflow_id": str(ID),
        "entries": [manual, api_entry],
    }
    assert len(response["entries"]) == 4
    api.refuse.assert_not_called()


@pytest.mark.parametrize("entries", [{}, ["invalid"], [{"trigger": {}}]])
async def test_malformed_owned_discovery_responses_fail_instead_of_hiding_entries(
    entries: object,
) -> None:
    api = MagicMock(spec=PlatformApi)
    api.request = AsyncMock(return_value={"entries": entries})
    tool = {tool.name: tool for tool in platform_tools(api)}["get_workflow_input_schema"]
    with pytest.raises(TypeError, match="Workflow input-schema"):
        await tool.function(workflow_id=ID)
