"""MCP Apps at the toolset (#3450): which tool returns keep their page, and how.

The server-side records come from Pydantic AI's `MCPToolset`, which attaches one
to every tool that names a `ui://` page whether or not anyone asked. These tests
pin what AgenticOS does with it: drop it where the connection's switch is off,
stamp it with the connection and the run's policy where it is on, and keep it
small enough to store with the call.
"""

import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastmcp import Client
from mcp.types import Tool
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ToolReturn

from app.agents.mcp import McpServerSpec, _make_toolset, apps_served, probe_mcp_server
from app.agents.mcp_apps import (
    APP_MIME_TYPE,
    MAX_PAGE_EVENT_BYTES,
    MAX_RECORD_BYTES,
    UI_EXTENSION,
    McpAppResults,
    app_client,
    app_record,
    page_view,
    stored_record,
    visible_to_model,
)

pytestmark = pytest.mark.anyio

PAGE = "ui://charts/viewer.html"


def _raw(**result: Any) -> dict[str, Any]:
    """What `MCPToolset` attaches under `metadata["mcp_app"]` for a tool with a page."""
    return {
        "resource_uri": PAGE,
        "tool_input": {"source": "asset:1"},
        "result": {"content": [{"type": "text", "text": "5 rows"}], "isError": False, **result},
        "toolset_id": "mcp-charts",
    }


def _stored(**overrides: Any) -> dict[str, Any]:
    return {
        "resource_uri": PAGE,
        "tool_input": {"source": "asset:1"},
        "result": {"content": [], "isError": False},
        "connection_id": str(uuid4()),
        "tool_name": "data_query",
        "allowed_tools": None,
        "approval": "writes",
        "tool_approval": {},
        **overrides,
    }


def _wrapping(returned: Any, **fields: Any) -> McpAppResults:
    inner = MagicMock()
    inner.call_tool = AsyncMock(return_value=returned)
    return McpAppResults(inner, **fields)


async def _call(toolset: McpAppResults) -> Any:
    return await toolset.call_tool("data_query", {"source": "asset:1"}, MagicMock(), MagicMock())


class TestReadingARecord:
    def test_a_stamped_record_reads_back_whole(self):
        record = _stored()

        assert app_record({"mcp_app": record}) == record
        assert stored_record(record) == record

    def test_the_toolsets_own_record_is_not_one_until_it_is_stamped(self):
        """Without the connection it names nothing to read a page through."""
        assert app_record({"mcp_app": _raw()}) is None

    def test_anything_else_is_no_record(self):
        assert app_record(None) is None
        assert app_record("mcp_app") is None
        assert app_record({}) is None
        assert stored_record(None) is None
        assert stored_record({"resource_uri": PAGE}) is None

    def test_the_browser_gets_everything_but_the_connection_and_policy(self):
        record = _stored()

        assert page_view(stored_record(record)) == {  # type: ignore[arg-type]
            "resource_uri": PAGE,
            "tool_input": record["tool_input"],
            "result": record["result"],
        }


class TestVisibility:
    @pytest.mark.parametrize(
        ("meta", "visible"),
        [
            (None, True),
            ({}, True),
            ({"ui": {"resourceUri": PAGE}}, True),
            ({"ui": {"visibility": ["model", "app"]}}, True),
            ({"ui": {"visibility": ["app"]}}, False),
            ({"ui": {"visibility": "app"}}, True),
        ],
    )
    def test_only_a_tool_listed_for_the_page_alone_is_hidden_from_the_model(self, meta, visible):
        assert visible_to_model(meta) is visible

    async def test_the_probe_leaves_a_page_only_tool_out_of_the_tools_to_pick(self, monkeypatch):
        """The model never sees it, so it is not one to put on a binding's list."""
        listed = Tool(name="data_query", input_schema={"type": "object"})
        hidden = Tool(
            name="widget_data",
            input_schema={"type": "object"},
            _meta={"ui": {"resourceUri": PAGE, "visibility": ["app"]}},
        )
        session = AsyncMock()
        session.list_tools = AsyncMock(return_value=MagicMock(tools=[listed, hidden]))

        @asynccontextmanager
        async def _open(*_: Any, **__: Any):
            yield session

        monkeypatch.setattr("app.agents.mcp.mcp_session", _open)

        tools = await probe_mcp_server("https://example.com/mcp")

        assert [tool.name for tool in tools] == ["data_query"]


class TestAppResults:
    async def test_a_plain_result_passes_through(self):
        assert await _call(_wrapping("5 rows", connection_id=uuid4())) == "5 rows"

    async def test_a_return_without_a_page_passes_through(self):
        returned = ToolReturn(return_value="5 rows", metadata={"other": 1})
        assert await _call(_wrapping(returned, connection_id=uuid4())) is returned
        bare = ToolReturn(return_value="5 rows")
        assert await _call(_wrapping(bare, connection_id=uuid4())) is bare

    async def test_with_pages_off_the_record_is_dropped(self):
        """No surface reads it then, and it can be megabytes in every run's history."""
        result = await _call(
            _wrapping(ToolReturn(return_value="5 rows", metadata={"mcp_app": _raw()}))
        )

        assert result == "5 rows"

    async def test_with_pages_off_whatever_else_the_return_carries_stays(self):
        kept = await _call(
            _wrapping(ToolReturn(return_value="5 rows", metadata={"mcp_app": _raw(), "trace": 1}))
        )
        assert isinstance(kept, ToolReturn)
        assert kept.metadata == {"trace": 1}

        with_content = await _call(
            _wrapping(
                ToolReturn(return_value="5 rows", content="see", metadata={"mcp_app": _raw()})
            )
        )
        assert isinstance(with_content, ToolReturn)
        assert with_content.metadata is None
        assert with_content.content == "see"

    async def test_with_pages_on_the_record_names_its_connection_and_the_runs_policy(self):
        connection = uuid4()
        toolset = _wrapping(
            ToolReturn(return_value="5 rows", metadata={"mcp_app": _raw(), "trace": 1}),
            connection_id=connection,
            allowed_tools=["data_query", "chart_show"],
            approval="all",
            tool_approval={"data_query": "never"},
        )

        result = await _call(toolset)

        assert isinstance(result, ToolReturn)
        assert result.return_value == "5 rows"
        assert result.metadata["trace"] == 1
        assert app_record(result.metadata) == {
            "resource_uri": PAGE,
            "tool_input": {"source": "asset:1"},
            "result": {"content": [{"type": "text", "text": "5 rows"}], "isError": False},
            "connection_id": str(connection),
            "tool_name": "data_query",
            "allowed_tools": ["data_query", "chart_show"],
            "approval": "all",
            "tool_approval": {"data_query": "never"},
        }

    async def test_binary_content_is_not_kept_for_the_page(self):
        raw = _raw()
        raw["result"]["content"] = [
            {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"},
            {"type": "audio", "data": "aGVsbG8=", "mimeType": "audio/wav"},
            {"type": "resource", "resource": {"uri": "file:///a", "blob": "aGVsbG8="}},
            {"type": "resource", "resource": {"uri": "file:///b", "text": "kept"}},
            {"type": "text", "text": "kept"},
        ]
        result = await _call(
            _wrapping(
                ToolReturn(return_value="x", metadata={"mcp_app": raw}), connection_id=uuid4()
            )
        )

        content = app_record(result.metadata)["result"]["content"]  # type: ignore[index]
        assert "aGVsbG8=" not in json.dumps(content)
        assert content[3] == {"type": "resource", "resource": {"uri": "file:///b", "text": "kept"}}
        assert content[4] == {"type": "text", "text": "kept"}

    async def test_a_result_without_a_content_list_is_kept_as_it_is(self):
        raw = _raw()
        raw["result"] = {"structuredContent": {"rows": []}, "isError": False}
        result = await _call(
            _wrapping(
                ToolReturn(return_value="x", metadata={"mcp_app": raw}), connection_id=uuid4()
            )
        )

        assert app_record(result.metadata)["result"] == raw["result"]  # type: ignore[index]

    async def test_a_record_too_large_to_store_shows_as_text_only(self):
        raw = _raw(structuredContent={"rows": ["x" * MAX_RECORD_BYTES]})

        result = await _call(
            _wrapping(
                ToolReturn(return_value="5 rows", metadata={"mcp_app": raw}), connection_id=uuid4()
            )
        )

        assert result == "5 rows"

    async def test_a_record_the_toolset_did_not_write_whole_is_left_alone(self):
        returned = ToolReturn(return_value="5 rows", metadata={"mcp_app": {"resource_uri": PAGE}})

        assert await _call(_wrapping(returned, connection_id=uuid4())) is returned


class TestServing:
    def _spec(self, **overrides: Any) -> McpServerSpec:
        fields: dict[str, Any] = {
            "name": "charts",
            "url": "https://charts.example.com/mcp",
            "headers": {"Authorization": "Bearer t"},
            "mcp_apps": True,
            "source_connection_id": uuid4(),
        }
        return McpServerSpec(**(fields | overrides))

    def test_pages_are_served_where_switched_on_over_streamable_http(self):
        assert apps_served(self._spec()) is True

    @pytest.mark.parametrize(
        "overrides",
        [
            {"mcp_apps": False},
            {"in_process": True},
            {"source_connection_id": None},
            {"url": "https://charts.example.com/sse"},
        ],
    )
    def test_and_nowhere_else(self, overrides):
        assert apps_served(self._spec(**overrides)) is False

    def test_a_server_with_pages_gets_a_client_that_says_so_and_reads_a_page_whole(self):
        spec = self._spec()

        toolset = _make_toolset(spec)
        apps = toolset.wrapped.wrapped.wrapped.wrapped
        assert isinstance(apps, McpAppResults)
        assert apps.connection_id == spec.source_connection_id
        server = apps.wrapped
        assert isinstance(server, MCPToolset)
        client = server.client
        assert isinstance(client, Client)
        assert client.transport.max_sse_event_size == MAX_PAGE_EVENT_BYTES
        assert client.transport.headers == {"Authorization": "Bearer t"}
        assert server.tool_error_behavior == "failed"

    def test_a_server_without_pages_drops_their_records(self):
        toolset = _make_toolset(self._spec(mcp_apps=False))

        apps = toolset.wrapped.wrapped.wrapped.wrapped
        assert isinstance(apps, McpAppResults)
        assert apps.connection_id is None

    def test_the_client_announces_the_extension_with_the_page_type(self):
        client = app_client("https://charts.example.com/mcp", {}, init_timeout=3)

        [extension] = client._extensions_arg  # the extensions this client advertises
        assert extension.identifier == UI_EXTENSION
        assert extension.settings() == {"mimeTypes": [APP_MIME_TYPE]}
