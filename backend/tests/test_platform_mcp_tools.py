"""Each platform MCP tool is exactly one public API call, made as the caller (#2058)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken

from app.services.platform_mcp._api import PlatformApi
from app.services.platform_mcp._oauth import PlatformOAuthProvider
from app.services.platform_mcp._tools import platform_tools

pytestmark = pytest.mark.anyio

ORG = str(uuid.uuid4())
AGENT = uuid.uuid4()
KB = uuid.uuid4()
RUN = uuid.uuid4()


@pytest.fixture
def api() -> MagicMock:
    stub = MagicMock()
    stub.request = AsyncMock(return_value={"organization_id": ORG})
    return stub


@pytest.fixture
def server(api: MagicMock) -> FastMCP:
    server = FastMCP(name="test")
    for tool in platform_tools(api):
        server.tool(tool.function)
    return server


@pytest.mark.parametrize(
    ("tool", "arguments", "call"),
    [
        ("whoami", {}, ("GET", "/me/permissions", {})),
        ("list_agents", {}, ("GET", "/agents", {"params": {"limit": 50, "skip": 0}})),
        ("get_agent", {"agent_id": str(AGENT)}, ("GET", f"/agents/{AGENT}", {})),
        (
            "create_agent_draft",
            {"name": "Bot", "instructions": "Be brief.", "description": "A bot"},
            (
                "POST",
                "/agents",
                {
                    "json": {
                        "spec": {
                            "name": "Bot",
                            "instructions": "Be brief.",
                            "capabilities": [{"id": "ask_user"}],
                            "description": "A bot",
                        }
                    }
                },
            ),
        ),
        (
            "create_agent_draft",
            {"name": "Bot", "instructions": "Be brief."},
            (
                "POST",
                "/agents",
                {
                    "json": {
                        "spec": {
                            "name": "Bot",
                            "instructions": "Be brief.",
                            "capabilities": [{"id": "ask_user"}],
                        }
                    }
                },
            ),
        ),
        (
            "run_agent",
            {"agent_id": str(AGENT), "prompt": "hi", "conversation_id": str(RUN)},
            (
                "POST",
                f"/agents/{AGENT}/run",
                {"json": {"prompt": "hi", "conversation_id": str(RUN)}},
            ),
        ),
        (
            "run_agent",
            {"agent_id": str(AGENT), "prompt": "hi"},
            ("POST", f"/agents/{AGENT}/run", {"json": {"prompt": "hi"}}),
        ),
        (
            "list_runs",
            {"agent_id": str(AGENT)},
            ("GET", "/runs", {"params": {"limit": 20, "skip": 0, "agent_id": str(AGENT)}}),
        ),
        ("list_runs", {}, ("GET", "/runs", {"params": {"limit": 20, "skip": 0}})),
        ("get_run", {"run_id": str(RUN)}, ("GET", f"/runs/{RUN}", {})),
        ("list_knowledge_bases", {}, ("GET", "/kb", {})),
        (
            "create_knowledge_base",
            {"name": "Policies", "description": "HR"},
            ("POST", "/kb", {"json": {"name": "Policies", "scope": "org", "description": "HR"}}),
        ),
        (
            "create_knowledge_base",
            {"name": "Policies"},
            ("POST", "/kb", {"json": {"name": "Policies", "scope": "org"}}),
        ),
        (
            "add_document",
            {"kb_id": str(KB), "filename": "a.md", "content": "# Hi"},
            ("POST", f"/kb/{KB}/documents", {"files": {"file": ("a.md", b"# Hi", "text/plain")}}),
        ),
        (
            "search_knowledge",
            {"collection_name": "policies", "query": "refunds"},
            (
                "POST",
                "/rag/search",
                {"json": {"collection_name": "policies", "query": "refunds", "limit": 4}},
            ),
        ),
        ("list_skills", {}, ("GET", "/skills", {})),
        ("list_members", {}, ("GET", f"/orgs/{ORG}/members", {})),
        (
            "invite_member",
            {"email": "ada@example.com"},
            (
                "POST",
                f"/orgs/{ORG}/invitations",
                {"json": {"email": "ada@example.com", "role": "member"}},
            ),
        ),
    ],
)
async def test_each_tool_is_one_public_api_call(
    server: FastMCP, api: MagicMock, tool: str, arguments: dict[str, Any], call: tuple[Any, ...]
) -> None:
    await server.call_tool(tool, arguments)

    method, path, kwargs = call
    assert api.request.await_args.args == (method, path)
    assert api.request.await_args.kwargs == kwargs


def _token() -> AccessToken:
    return AccessToken(token="aos_0123abcdsecret", client_id="aos_0123abcd", scopes=[])


def _raise(message: str) -> dict[str, Any]:
    raise ToolError(message)


def _api(handler: Any, token: str | None = "aos_0123abcdsecret") -> PlatformApi:
    api = PlatformApi(MagicMock(), token=lambda: token, on_refusal=_raise)
    api._transport = httpx.MockTransport(handler)
    return api


class TestTheInProcessCall:
    async def test_the_caller_s_token_is_sent_and_the_answer_returned(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        answer = await _api(handler).request("GET", "/agents")

        assert answer == {"ok": True}
        assert seen[0].headers["authorization"] == "Bearer aos_0123abcdsecret"
        assert seen[0].url.path == "/api/v1/agents"

    async def test_a_refusal_becomes_a_tool_error_carrying_the_api_s_reason(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                json={
                    "error": {"code": "AUTHORIZATION_ERROR", "message": "Insufficient permissions"}
                },
            )

        with pytest.raises(ToolError, match="403 AUTHORIZATION_ERROR: Insufficient permissions"):
            await _api(handler).request("POST", "/agents", json={})

    async def test_an_unexpected_error_body_still_says_something(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, json=["not", "an", "envelope"])

        with pytest.raises(ToolError, match="502 ERROR: The request was refused"):
            await _api(handler).request("GET", "/agents")

    async def test_no_content_is_none(self) -> None:
        answer = await _api(lambda request: httpx.Response(204)).request("DELETE", "/x")

        assert answer is None

    async def test_an_unauthenticated_call_never_reaches_the_api(self) -> None:
        with pytest.raises(ToolError, match="authenticated"):
            await _api(lambda request: httpx.Response(200, json={}), token=None).request(
                "GET", "/agents"
            )


class TestTheVerifier:
    async def test_a_session_jwt_is_not_an_mcp_credential(self) -> None:
        assert await PlatformOAuthProvider().load_access_token("eyJhbGciOiJIUzI1NiJ9.e30.x") is None

    @pytest.mark.security
    async def test_a_key_the_platform_refuses_opens_no_session(self) -> None:
        from app.core.exceptions import AuthenticationError

        with (
            patch("app.services.platform_mcp._oauth.get_db_context") as db_context,
            patch(
                "app.services.platform_mcp._oauth.ApiKeyService.authenticate",
                new=AsyncMock(side_effect=AuthenticationError(message="revoked")),
            ),
        ):
            db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)
            assert await PlatformOAuthProvider().load_access_token("aos_0123abcdsecret") is None

    async def test_a_token_this_provider_did_not_load_has_no_grant_to_revoke(self) -> None:
        with patch("app.services.platform_mcp._oauth.get_db_context") as db_context:
            await PlatformOAuthProvider().revoke_token(_token())

        db_context.assert_not_called()


class TestChainedCalls:
    async def test_a_refused_identity_is_passed_on_rather_than_used(self) -> None:
        """`list_members` and `invite_member` first ask who the caller is; a refusal
        there is the answer, not a key to index."""
        refusal = {"refused": "401 AUTHENTICATION_ERROR: gone"}
        api = MagicMock()
        api.request = AsyncMock(return_value=refusal)
        tools = {tool.name: tool for tool in platform_tools(api)}

        assert await tools["list_members"].function() == refusal
        assert await tools["invite_member"].function(email="ada@example.com") == refusal
        assert tools["invite_member"].writes and not tools["list_members"].writes
        assert tools["whoami"].summary.startswith("Which organization")
