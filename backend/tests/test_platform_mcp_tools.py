"""Each platform MCP tool is exactly one public API call, made as the caller (#2058)."""

import uuid
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.exceptions import ValidationError as MCPValidationError
from fastmcp.server.auth import AccessToken

from app.services.platform_mcp import _unreachable, platform_tool_catalog
from app.services.platform_mcp._api import PlatformApi
from app.services.platform_mcp._oauth import PlatformOAuthProvider
from app.services.platform_mcp._tools import platform_tools

pytestmark = pytest.mark.anyio

# Fixed, not `uuid4()`: the paths below are test parameters, and a parameter
# that differs between xdist workers fails the whole collection.
ORG = "00000000-0000-4000-8000-00000000000a"
AGENT = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
KB = uuid.UUID("00000000-0000-4000-8000-0000000000b1")
RUN = uuid.UUID("00000000-0000-4000-8000-0000000000c1")


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


CALLS: list[tuple[str, dict[str, Any], tuple[Any, ...]]] = [
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
    ("get_spend", {}, ("GET", "/spend", {"params": {"days": 30}})),
    ("list_knowledge_bases", {}, ("GET", "/kb", {})),
    ("list_embedding_models", {}, ("GET", "/rag/embedding-models", {})),
    (
        "create_knowledge_base",
        {
            "name": "Policies",
            "embedding_provider": "openai",
            "embedding_secret_id": str(KB),
            "embedding_model": "text-embedding-3-small",
            "description": "HR",
        },
        (
            "POST",
            "/kb",
            {
                "json": {
                    "name": "Policies",
                    "scope": "org",
                    "embedding_provider": "openai",
                    "embedding_secret_id": str(KB),
                    "embedding_model": "text-embedding-3-small",
                    "description": "HR",
                }
            },
        ),
    ),
    (
        "create_knowledge_base",
        {"name": "Policies", "embedding_provider": "ollama", "embedding_endpoint_id": str(KB)},
        (
            "POST",
            "/kb",
            {
                "json": {
                    "name": "Policies",
                    "scope": "org",
                    "embedding_provider": "ollama",
                    "embedding_endpoint_id": str(KB),
                }
            },
        ),
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
    (
        "list_skills",
        {"skip": 50},
        ("GET", "/skills", {"params": {"limit": 50, "skip": 50}}),
    ),
    ("list_capabilities", {}, ("GET", "/agents/capabilities", {})),
    (
        "create_agent_draft",
        {"name": "Bot", "instructions": "Hi", "capabilities": ["web_research", "ask_user"]},
        (
            "POST",
            "/agents",
            {
                "json": {
                    "spec": {
                        "name": "Bot",
                        "instructions": "Hi",
                        "capabilities": [{"id": "ask_user"}, {"id": "web_research"}],
                    }
                }
            },
        ),
    ),
    (
        "list_members",
        {"limit": 10},
        ("GET", f"/orgs/{ORG}/members", {"params": {"limit": 10, "skip": 0}}),
    ),
    (
        "invite_member",
        {"email": "ada@example.com"},
        (
            "POST",
            f"/orgs/{ORG}/invitations",
            {"json": {"email": "ada@example.com", "role": "member"}},
        ),
    ),
    (
        "create_agent_draft",
        {
            "name": "Bot",
            "instructions": "Hi",
            "model_profile_id": str(KB),
            "starters": ["What can you do?"],
        },
        (
            "POST",
            "/agents",
            {
                "json": {
                    "spec": {
                        "name": "Bot",
                        "instructions": "Hi",
                        "capabilities": [{"id": "ask_user"}],
                        "model_profile_id": str(KB),
                        "starters": ["What can you do?"],
                    }
                }
            },
        ),
    ),
    (
        "test_agent_draft",
        {"agent_id": str(AGENT), "prompt": "hi"},
        ("POST", f"/agents/{AGENT}/run", {"json": {"prompt": "hi", "draft": True}}),
    ),
    (
        "test_agent_draft",
        {"agent_id": str(AGENT), "prompt": "and?", "conversation_id": str(RUN)},
        (
            "POST",
            f"/agents/{AGENT}/run",
            {"json": {"prompt": "and?", "draft": True, "conversation_id": str(RUN)}},
        ),
    ),
    (
        "publish_agent",
        {"agent_id": str(AGENT), "note": "First version"},
        ("POST", f"/agents/{AGENT}/publish", {"json": {"note": "First version"}}),
    ),
    (
        "publish_agent",
        {"agent_id": str(AGENT)},
        ("POST", f"/agents/{AGENT}/publish", {"json": {}}),
    ),
    ("list_models", {}, ("GET", "/providers/model-profiles", {})),
    ("list_routines", {}, ("GET", "/triggers", {"params": {"limit": 50}})),
    ("list_routines", {"agent_id": str(AGENT)}, ("GET", f"/agents/{AGENT}/triggers", {})),
    (
        "create_routine",
        {
            "agent_id": str(AGENT),
            "prompt": "Summarise the week's AI news in English.",
            "cron_expression": "0 7 * * 1",
            "name": "Weekly AI news",
        },
        (
            "POST",
            f"/agents/{AGENT}/triggers",
            {
                "json": {
                    "prompt": "Summarise the week's AI news in English.",
                    "runs_as_creator": True,
                    "name": "Weekly AI news",
                    "schedule_kind": "cron",
                    "cron_expression": "0 7 * * 1",
                }
            },
        ),
    ),
    (
        "create_routine",
        {
            "agent_id": str(AGENT),
            "prompt": "Check the site.",
            "every_minutes": 60,
            "runs_as_me": False,
        },
        (
            "POST",
            f"/agents/{AGENT}/triggers",
            {
                "json": {
                    "prompt": "Check the site.",
                    "runs_as_creator": False,
                    "interval_seconds": 3600,
                }
            },
        ),
    ),
    (
        "update_routine",
        {
            "agent_id": str(AGENT),
            "routine_id": str(RUN),
            "active": False,
            "prompt": "New",
            "name": "Renamed",
            "cron_expression": "0 8 * * *",
        },
        (
            "PATCH",
            f"/agents/{AGENT}/triggers/{RUN}",
            {
                "json": {
                    "is_active": False,
                    "prompt": "New",
                    "name": "Renamed",
                    "schedule_kind": "cron",
                    "cron_expression": "0 8 * * *",
                }
            },
        ),
    ),
    (
        "update_routine",
        {"agent_id": str(AGENT), "routine_id": str(RUN), "every_minutes": 30},
        (
            "PATCH",
            f"/agents/{AGENT}/triggers/{RUN}",
            {"json": {"schedule_kind": "interval", "interval_seconds": 1800}},
        ),
    ),
    (
        "run_routine_now",
        {"agent_id": str(AGENT), "routine_id": str(RUN)},
        ("POST", f"/agents/{AGENT}/triggers/{RUN}/run", {}),
    ),
    (
        "search_mcp_servers",
        {"query": "notion"},
        ("GET", "/agents/mcp-servers", {"params": {"q": "notion", "limit": 10}}),
    ),
    ("list_my_connections", {"include_tools": True}, ("GET", "/me/mcp-connections", {})),
    (
        "set_my_language",
        {"locale": "en"},
        ("PUT", "/users/me/locale", {"json": {"locale": "en"}}),
    ),
    (
        "read_conversation",
        {"conversation_id": "00000000-0000-0000-0000-000000000001"},
        (
            "GET",
            "/conversations/00000000-0000-0000-0000-000000000001/transcript",
            {"params": {"limit": 100, "skip": 0}},
        ),
    ),
    # Only what the person said: a field left out stays as the account has it.
    (
        "set_my_profile",
        {"job_title": "Head of sales"},
        ("PATCH", "/users/me/agent-context", {"json": {"job_title": "Head of sales"}}),
    ),
    (
        "create_skill",
        {"name": "weekly-digest", "description": "When asked for the digest", "content": "1. Read"},
        (
            "POST",
            "/skills",
            {
                "json": {
                    "name": "weekly-digest",
                    "description": "When asked for the digest",
                    "content": "1. Read",
                }
            },
        ),
    ),
]


@pytest.mark.parametrize(("tool", "arguments", "call"), CALLS)
async def test_each_tool_is_one_public_api_call(
    server: FastMCP, api: MagicMock, tool: str, arguments: dict[str, Any], call: tuple[Any, ...]
) -> None:
    await server.call_tool(tool, arguments)

    method, path, kwargs = call
    assert api.request.await_args.args == (method, path)
    assert api.request.await_args.kwargs == kwargs


@pytest.mark.parametrize(
    ("method", "path"), sorted({(call[0], call[1]) for _tool, _args, call in CALLS})
)
def test_every_call_reaches_a_public_route(method: str, path: str) -> None:
    """A tool is a call to the public API, so the route has to exist and admit a key.

    The table above checks the call a tool makes, not that anything answers it:
    `list_models` once asked for `/model-profiles`, which is mounted under
    `/providers`, and every agent-building conversation hit a 404 (#2301).
    """
    import re

    from app.api.public_api import public_operations
    from app.core.config import settings
    from app.main import app

    full = f"{settings.API_V1_STR}{path}"
    public = [
        template
        for verb, template in public_operations(app.routes)
        if verb == method.lower() and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), full)
    ]

    assert public, f"no public route answers {method} {path}"


class TestListingMyConnections:
    """Whether a service is connected needs its name, not the tools it offers."""

    LISTING: ClassVar[dict[str, Any]] = {
        "items": [
            {
                "name": "stripe",
                "catalog_key": "stripe",
                "authorized": True,
                "allowed_tools": ["list_customers"],
                "last_tools": [{"name": "list_customers"}, {"name": "create_refund"}],
            }
        ],
        "total": 1,
    }

    async def test_the_tools_are_left_out_by_default(self, server: FastMCP, api: MagicMock) -> None:
        api.request.return_value = self.LISTING

        result = await server.call_tool("list_my_connections", {})

        assert result.structured_content == {
            "items": [{"name": "stripe", "catalog_key": "stripe", "authorized": True}],
            "total": 1,
        }

    async def test_the_tools_come_when_asked_for(self, server: FastMCP, api: MagicMock) -> None:
        api.request.return_value = self.LISTING

        result = await server.call_tool("list_my_connections", {"include_tools": True})

        assert result.structured_content == self.LISTING


class TestUndoingADraft:
    async def test_the_server_is_asked_to_delete_only_a_draft(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request.side_effect = [None]

        result = await server.call_tool("discard_agent_draft", {"agent_id": str(AGENT)})

        # One call: the server checks ownership and publication on the locked row,
        # so a key issued only to edit needs no read first.
        assert [c.args for c in api.request.await_args_list] == [("DELETE", f"/agents/{AGENT}")]
        assert api.request.await_args.kwargs == {"params": {"draft_only": "true"}}
        assert result.structured_content == {"discarded": str(AGENT)}

    async def test_a_refusal_is_passed_back_untouched(self, api: MagicMock) -> None:
        refused = {"refused": "Only a never-published draft you created can be undone"}
        api.request.side_effect = [refused]
        tool = {t.name: t for t in platform_tools(api)}["discard_agent_draft"]

        assert await tool.function(agent_id=AGENT) == refused


class TestEditingADraft:
    """`update_agent_draft` reads the draft and writes it back with only what was asked."""

    async def test_only_what_was_passed_changes(self, server: FastMCP, api: MagicMock) -> None:
        skill = uuid.uuid4()
        draft = {
            "name": "Bot",
            "instructions": "Old",
            "capabilities": [{"id": "ask_user"}, {"id": "clock", "config": {"timezone": "UTC"}}],
            "skill_ids": [],
        }
        api.request.side_effect = [{"id": str(AGENT), "draft_spec": draft}, {"id": str(AGENT)}]

        await server.call_tool(
            "update_agent_draft",
            {
                "agent_id": str(AGENT),
                "instructions": "New",
                "description": "Answers refunds",
                "add_capabilities": ["knowledge", "clock", "knowledge"],
                "remove_capabilities": ["ask_user"],
                "model_profile_id": str(KB),
                "skill_ids": [str(skill)],
                "collection_ids": [str(KB)],
                "starters": ["How do refunds work?"],
            },
        )

        read, write = api.request.await_args_list
        assert read.args == ("GET", f"/agents/{AGENT}")
        assert write.args == ("PUT", f"/agents/{AGENT}/draft")
        assert write.kwargs["json"]["spec"] == {
            "name": "Bot",
            "instructions": "New",
            "description": "Answers refunds",
            "model_profile_id": str(KB),
            # A binding already there keeps its config; a new one takes defaults.
            "capabilities": [{"id": "clock", "config": {"timezone": "UTC"}}, {"id": "knowledge"}],
            "skill_ids": [str(skill)],
            "collection_ids": [str(KB)],
            "starters": ["How do refunds work?"],
        }

    async def test_a_draft_left_alone_is_written_back_as_it_was(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        draft = {"name": "Bot", "instructions": "Old", "capabilities": [{"id": "ask_user"}]}
        api.request.side_effect = [{"draft_spec": draft}, {}]

        await server.call_tool("update_agent_draft", {"agent_id": str(AGENT)})

        assert api.request.await_args.kwargs["json"]["spec"] == draft

    async def test_a_refused_read_is_the_answer(self, api: MagicMock) -> None:
        refused = {"refused": "404 NOT_FOUND: Agent not found"}
        api.request.side_effect = [refused]
        tool = {t.name: t for t in platform_tools(api)}["update_agent_draft"]

        assert await tool.function(agent_id=AGENT, instructions="x") == refused
        assert api.request.await_count == 1


class TestRemovingARoutine:
    async def test_a_removal_says_which_routine_went(self, server: FastMCP, api: MagicMock) -> None:
        api.request.side_effect = [None]

        result = await server.call_tool(
            "delete_routine", {"agent_id": str(AGENT), "routine_id": str(RUN)}
        )

        assert api.request.await_args.args == ("DELETE", f"/agents/{AGENT}/triggers/{RUN}")
        assert result.structured_content == {"deleted": str(RUN)}

    async def test_a_refusal_is_passed_back_untouched(self, api: MagicMock) -> None:
        refused = {"refused": "Only its creator may remove it"}
        api.request.side_effect = [refused]
        tool = {t.name: t for t in platform_tools(api)}["delete_routine"]

        assert await tool.function(agent_id=AGENT, routine_id=RUN) == refused


class TestWhatNeverWaitsForApproval:
    def test_only_the_askers_own_language_is_ungated(self) -> None:
        """Switching the console's language changes the asker's own account on
        their word (#2301); every other write - publishing and creating a skill
        above all - is held."""
        tools = {tool.name: tool for tool in platform_tool_catalog()}

        assert {name for name, tool in tools.items() if tool.ungated} == {"set_my_language"}
        assert tools["set_my_language"].writes

    @pytest.mark.security
    def test_saving_the_profile_every_agent_is_told_waits_for_approval(self) -> None:
        """Codex on #2324: what it saves is appended to every agent's instructions,
        so a page that injected the call would otherwise persist into later runs."""
        tools = {tool.name: tool for tool in platform_tool_catalog()}

        assert tools["set_my_profile"].writes
        assert not tools["set_my_profile"].ungated
        assert tools["create_skill"].writes and not tools["create_skill"].ungated
        assert tools["publish_agent"].writes and not tools["publish_agent"].ungated

    def test_reading_a_whole_past_conversation_waits_like_a_write(self) -> None:
        """Codex on #2324: `list_runs` names the conversations and this returns
        them, so a page that injected both calls could carry one off."""
        tools = {tool.name: tool for tool in platform_tool_catalog()}

        assert {name for name, tool in tools.items() if tool.held} == {"read_conversation"}
        assert not tools["read_conversation"].writes
        assert not tools["get_run"].held

    async def test_a_held_read_is_announced_as_no_read_only_tool(self) -> None:
        """The read-only hint is what the `writes` policy reads to let a call through."""
        from app.services.platform_mcp import build_platform_mcp

        server, _ = build_platform_mcp(MagicMock())
        listed = {tool.name: tool for tool in await server.list_tools()}

        assert listed["read_conversation"].annotations.readOnlyHint is False
        assert listed["get_run"].annotations.readOnlyHint is True

    def test_the_agent_layer_names_the_same_set(self) -> None:
        from app.agents.mcp import PLATFORM_UNGATED_TOOLS
        from app.services.platform_mcp._tools import UNGATED

        assert PLATFORM_UNGATED_TOOLS == UNGATED


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


async def test_refuse_answers_the_way_an_api_refusal_does() -> None:
    with pytest.raises(ToolError, match="nope"):
        _api(lambda request: httpx.Response(200)).refuse("nope")


class TestTheCatalogTheBuilderLists:
    """`GET /agents/platform-mcp-tools`: what a binding chooses from (#2190)."""

    def test_it_is_the_server_s_own_tools_with_their_write_marks(self) -> None:
        catalog = {tool.name: tool for tool in platform_tool_catalog()}

        assert catalog["list_agents"].writes is False
        assert catalog["create_agent_draft"].writes is True
        assert catalog["whoami"].summary.startswith("Which organization")

    async def test_describing_a_tool_can_never_run_it(self) -> None:
        """The catalog's API answers nothing: a call would be a bug, so it says so."""
        [whoami] = [tool for tool in platform_tool_catalog() if tool.name == "whoami"]

        with pytest.raises(ToolError, match="needs an authenticated caller"):
            await whoami.function()

    async def test_the_route_lists_every_tool_with_its_write_mark(self) -> None:
        from app.api.routes.v1.agents import list_platform_mcp_tools

        listed = await list_platform_mcp_tools()
        by_name = {item.name: item for item in listed.items}

        assert listed.total == len(platform_tool_catalog()) == len(by_name)
        assert by_name["run_agent"].writes is True
        assert by_name["get_run"].writes is False

    async def test_the_api_behind_the_catalog_answers_nothing(self) -> None:
        with pytest.raises(RuntimeError, match="nothing is called"):
            await _unreachable({}, AsyncMock(), AsyncMock())


class TestConfiguredDrafts:
    async def test_create_accepts_configured_capabilities_and_resource_bindings(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        await server.call_tool(
            "create_agent_draft",
            {
                "name": "Developer",
                "instructions": "Run tests before reporting success.",
                "capabilities": [
                    "sandbox",
                    {
                        "id": "sandbox",
                        "config": {
                            "backend": "service",
                            "connection_id": str(KB),
                            "include_execute": True,
                        },
                        "approval": "required",
                    },
                    "ask_user",
                ],
                "mcp_servers": [{"account": "personal", "catalog_key": "github"}],
                "skill_ids": [str(KB)],
                "collection_ids": [str(KB)],
            },
        )
        spec = api.request.await_args.kwargs["json"]["spec"]
        assert spec["capabilities"] == [
            {"id": "ask_user"},
            {
                "id": "sandbox",
                "config": {
                    "backend": "service",
                    "connection_id": str(KB),
                    "include_execute": True,
                },
                "approval": "required",
            },
        ]
        assert spec["mcp_servers"][0]["catalog_key"] == "github"
        assert spec["skill_ids"] == spec["collection_ids"] == [str(KB)]

    async def test_configuring_an_existing_binding_preserves_other_settings(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        draft = {
            "name": "Developer",
            "instructions": "Keep",
            "capabilities": [
                {
                    "id": "sandbox",
                    "config": {"backend": "state"},
                    "approval": "required",
                    "enabled": False,
                },
                {"id": "clock"},
            ],
            "mcp_servers": [],
        }
        api.request.side_effect = [{"draft_spec": draft}, {}]
        await server.call_tool(
            "update_agent_draft",
            {
                "agent_id": str(AGENT),
                "add_capabilities": [
                    {"id": "sandbox", "config": {"backend": "service", "include_execute": True}},
                    "sandbox",
                ],
                "mcp_servers": [
                    {
                        "account": "organization",
                        "connection_id": str(KB),
                        "allowed_tools": ["get_file"],
                    }
                ],
            },
        )
        spec = api.request.await_args.kwargs["json"]["spec"]
        assert spec["capabilities"] == [
            {
                "id": "sandbox",
                "config": {"backend": "service", "include_execute": True},
                "approval": "required",
                "enabled": False,
            },
            {"id": "clock"},
        ]
        assert spec["instructions"] == "Keep"
        assert spec["mcp_servers"][0]["connection_id"] == str(KB)
        assert spec["mcp_servers"][0]["allowed_tools"] == ["get_file"]
        assert draft["capabilities"][0]["config"] == {"backend": "state"}

    async def test_an_explicit_null_clears_a_binding_secret_reference(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request.side_effect = [
            {
                "draft_spec": {
                    "capabilities": [
                        {"id": "media", "secret_id": str(KB), "approval": "required"},
                    ]
                }
            },
            {},
        ]
        await server.call_tool(
            "update_agent_draft",
            {
                "agent_id": str(AGENT),
                "add_capabilities": [{"id": "media", "secret_id": None}],
            },
        )
        spec = api.request.await_args.kwargs["json"]["spec"]
        assert spec["capabilities"] == [{"id": "media", "secret_id": None, "approval": "required"}]

    async def test_empty_config_and_mcp_list_explicitly_reset_them(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        api.request.side_effect = [
            {
                "draft_spec": {
                    "capabilities": [
                        {"id": "sandbox", "config": {"backend": "service"}},
                    ],
                    "mcp_servers": [{"account": "personal", "catalog_key": "github"}],
                }
            },
            {},
        ]
        await server.call_tool(
            "update_agent_draft",
            {
                "agent_id": str(AGENT),
                "add_capabilities": [{"id": "sandbox", "config": {}}],
                "mcp_servers": [],
            },
        )
        spec = api.request.await_args.kwargs["json"]["spec"]
        assert spec["capabilities"] == [{"id": "sandbox", "config": {}}]
        assert spec["mcp_servers"] == []

    @pytest.mark.parametrize(
        "tool,arguments,path",
        [
            ("list_sandbox_connections", {}, "/sandbox-connections"),
            ("list_sandbox_runtimes", {}, "/sandbox-connections/runtimes"),
            ("get_sandbox_policy", {"connection_id": str(KB)}, f"/sandbox-connections/{KB}/policy"),
            ("list_org_connections", {}, "/mcp-connections"),
        ],
    )
    async def test_discovery_calls_the_public_api_as_a_read(
        self, server: FastMCP, api: MagicMock, tool: str, arguments: dict[str, str], path: str
    ) -> None:
        await server.call_tool(tool, arguments)
        api.request.assert_awaited_once_with("GET", path)
        assert not {item.name: item for item in platform_tools(api)}[tool].writes

    async def test_a_personal_connection_id_is_refused_before_writing(
        self, server: FastMCP, api: MagicMock
    ) -> None:
        with pytest.raises(MCPValidationError, match="connection_id"):
            await server.call_tool(
                "create_agent_draft",
                {
                    "name": "Wrong",
                    "instructions": "Keep",
                    "mcp_servers": [
                        {"account": "personal", "catalog_key": "github", "connection_id": str(KB)},
                    ],
                },
            )
        api.request.assert_not_awaited()
