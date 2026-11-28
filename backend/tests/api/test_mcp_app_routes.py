"""The routes of an MCP Apps page (#3450): where it is served, and what it relays.

The service decides who may have what (`tests/test_mcp_app_service.py`); these pin
the wire: the page's isolation headers, the content route's order, and that the
relays reach the service with what the console sent.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.mcp_app import McpAppFrame, McpAppPage

pytestmark = pytest.mark.anyio

type OpenClient = Any


@pytest.fixture
def service() -> MagicMock:
    return MagicMock(
        frame=AsyncMock(return_value=McpAppFrame(url="https://content.example.com/x")),
        page=AsyncMock(return_value=McpAppPage(document=b"<!doctype html><script>1</script>")),
        call_tool=AsyncMock(return_value={"content": [], "isError": False}),
        read_resource=AsyncMock(return_value={"contents": []}),
    )


@pytest.fixture
def client(service: MagicMock, mock_redis: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_mcp_app_service] = lambda: service
    app.dependency_overrides[deps.limit_mcp_app_page] = lambda: None
    app.dependency_overrides[deps.limit_mcp_app_relay] = lambda: None

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _app_url(conversation_id: uuid.UUID, suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/conversations/{conversation_id}/tool-calls/toolu_01/app{suffix}"


class TestThePage:
    @pytest.mark.security
    async def test_it_is_served_in_a_sandbox_with_scripts_alone_and_no_network(
        self, client: OpenClient, service: MagicMock
    ) -> None:
        """No native dialogs: a third party's `prompt()` would carry this deployment's name."""
        app.dependency_overrides.pop(deps.get_auth_context)
        async with client() as http:
            response = await http.get(f"{settings.API_V1_STR}/artifact-content/mcp-app/tok")

        assert response.status_code == 200
        assert response.text == "<!doctype html><script>1</script>"
        service.page.assert_awaited_once_with("tok")
        policy = response.headers["content-security-policy"]
        assert policy.startswith("sandbox allow-scripts;")
        assert "allow-modals" not in policy
        assert "allow-same-origin" not in policy
        assert "connect-src 'none'" in policy
        assert f"frame-ancestors {settings.FRONTEND_URL.rstrip('/')}" in policy
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"


class TestTheRelays:
    async def test_a_reader_asks_for_the_pages_address(
        self, client: OpenClient, service: MagicMock
    ) -> None:
        conversation_id = uuid.uuid4()
        async with client() as http:
            response = await http.post(_app_url(conversation_id))

        assert response.status_code == 200
        assert response.json() == {"url": "https://content.example.com/x"}
        kwargs = service.frame.await_args.kwargs
        assert kwargs["conversation_id"] == conversation_id
        assert kwargs["tool_call_id"] == "toolu_01"

    async def test_a_tool_call_is_relayed_with_its_arguments(
        self, client: OpenClient, service: MagicMock
    ) -> None:
        async with client() as http:
            response = await http.post(
                _app_url(uuid.uuid4(), "/tools-call"),
                json={"name": "widget_data", "arguments": {"widget_id": "w1"}},
            )

        assert response.status_code == 200
        assert response.json() == {"content": [], "isError": False}
        kwargs = service.call_tool.await_args.kwargs
        assert (kwargs["name"], kwargs["arguments"]) == ("widget_data", {"widget_id": "w1"})

    async def test_a_tool_call_without_a_name_is_refused_before_the_service(
        self, client: OpenClient, service: MagicMock
    ) -> None:
        async with client() as http:
            response = await http.post(_app_url(uuid.uuid4(), "/tools-call"), json={"name": ""})

        assert response.status_code == 422
        service.call_tool.assert_not_awaited()

    async def test_a_resource_read_is_relayed(self, client: OpenClient, service: MagicMock) -> None:
        async with client() as http:
            response = await http.post(
                _app_url(uuid.uuid4(), "/resources-read"), json={"uri": "ui://charts/x.html"}
            )

        assert response.status_code == 200
        assert service.read_resource.await_args.kwargs["uri"] == "ui://charts/x.html"
