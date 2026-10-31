"""The Architect builds workflows and table state through the scoped public API."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.schemas.virtual_table import ColumnInput, RecordQuery, RecordUpdate, SchemaUpdate
from app.services.platform_mcp._api import PlatformApi
from app.services.platform_mcp._tools import platform_tools
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
