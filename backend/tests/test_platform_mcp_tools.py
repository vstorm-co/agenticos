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
    ("list_watches", {}, ("GET", "/me/watches", {})),
    (
        "create_watch",
        {
            "agent_id": str(AGENT),
            "connection_id": str(KB),
            "title": "Reviews",
            "instructions": "Waiting on me",
            "every_minutes": 60,
        },
        (
            "POST",
            "/me/watches",
            {
                "json": {
                    "agent_id": str(AGENT),
                    "connection_id": str(KB),
                    "title": "Reviews",
                    "instructions": "Waiting on me",
                    "interval_minutes": 60,
                    "urgent": False,
                    "ends_at": None,
                    "environment_id": None,
                    "pinned_version_id": None,
                }
            },
        ),
    ),
    (
        "create_watch",
        {
            "agent_id": str(AGENT),
            "connection_id": str(KB),
            "title": "Reviews",
            "instructions": "Waiting on me",
            "every_minutes": 60,
            "urgent": True,
            "ends_at": "2026-12-01T08:00:00Z",
            "environment_id": str(RUN),
        },
        (
            "POST",
            "/me/watches",
            {
                "json": {
                    "agent_id": str(AGENT),
                    "connection_id": str(KB),
                    "title": "Reviews",
                    "instructions": "Waiting on me",
                    "interval_minutes": 60,
                    "urgent": True,
                    "ends_at": "2026-12-01T08:00:00Z",
                    "environment_id": str(RUN),
                    "pinned_version_id": None,
                }
            },
        ),
    ),
    (
        "update_watch",
        {
            "watch_id": str(RUN),
            "active": False,
            "urgent": False,
            "clear_end": True,
            "clear_pin": True,
        },
        (
            "PATCH",
            f"/me/watches/{RUN}",
            {
                "json": {
                    "is_active": False,
                    "urgent": False,
                    "ends_at": None,
                    "pinned_version_id": None,
                }
            },
        ),
    ),
    (
        "update_watch",
        {
            "watch_id": str(RUN),
            "agent_id": str(AGENT),
            "pinned_version_id": str(KB),
            "review_sources": True,
            "title": "New title",
            "instructions": "Different purpose",
            "every_minutes": 180,
            "ends_at": "2026-12-01T08:00:00Z",
        },
        (
            "PATCH",
            f"/me/watches/{RUN}",
            {
                "json": {
                    "agent_id": str(AGENT),
                    "pinned_version_id": str(KB),
                    "environment_id": None,
                    "review_sources": True,
                    "title": "New title",
                    "instructions": "Different purpose",
                    "interval_minutes": 180,
                    "ends_at": "2026-12-01T08:00:00Z",
                }
            },
        ),
    ),
    (
        "update_watch",
        {"watch_id": str(RUN), "environment_id": str(KB)},
        (
            "PATCH",
            f"/me/watches/{RUN}",
            {"json": {"environment_id": str(KB), "pinned_version_id": None}},
        ),
    ),
    (
        "update_watch",
        {"watch_id": str(RUN), "clear_environment": True},
        ("PATCH", f"/me/watches/{RUN}", {"json": {"environment_id": None}}),
    ),
    (
        "create_watch",
        {
            "agent_id": str(AGENT),
            "connection_id": str(KB),
            "title": "Reviews",
            "instructions": "Waiting on me",
            "every_minutes": 60,
            "report_mode": "every_check",
            "notification_channels": [],
        },
        (
            "POST",
            "/me/watches",
            {
                "json": {
                    "agent_id": str(AGENT),
                    "connection_id": str(KB),
                    "title": "Reviews",
                    "instructions": "Waiting on me",
                    "interval_minutes": 60,
                    "urgent": False,
                    "ends_at": None,
                    "environment_id": None,
                    "pinned_version_id": None,
                    "report_mode": "every_check",
                    "notification_channels": [],
                }
            },
        ),
    ),
    (
        "update_watch",
        {"watch_id": str(RUN), "notification_channels": ["push"], "report_mode": "changes"},
        (
            "PATCH",
            f"/me/watches/{RUN}",
            {"json": {"notification_channels": ["push"], "report_mode": "changes"}},
        ),
    ),
    (
        "update_watch",
        {"watch_id": str(RUN), "inherit_notifications": True},
        ("PATCH", f"/me/watches/{RUN}", {"json": {"notification_channels": None}}),
    ),
    (
        "create_routine",
        {
            "agent_id": str(AGENT),
            "prompt": "Report",
            "every_minutes": 60,
            "notification_channels": [],
        },
        (
            "POST",
            f"/agents/{AGENT}/triggers",
            {
                "json": {
                    "prompt": "Report",
                    "runs_as_creator": True,
                    "interval_seconds": 3600,
                    "notification_channels": [],
                }
            },
        ),
    ),
    (
        "update_routine",
        {"agent_id": str(AGENT), "routine_id": str(RUN), "notification_channels": ["email"]},
        (
            "PATCH",
            f"/agents/{AGENT}/triggers/{RUN}",
            {"json": {"notification_channels": ["email"]}},
        ),
    ),
    (
        "update_routine",
        {"agent_id": str(AGENT), "routine_id": str(RUN), "inherit_notifications": True},
        ("PATCH", f"/agents/{AGENT}/triggers/{RUN}", {"json": {"notification_channels": None}}),
    ),
    ("whoami", {}, ("GET", "/me/permissions", {})),
    ("list_projects", {}, ("GET", "/projects", {"params": {"limit": 50, "skip": 0}})),
    (
        "list_projects",
        {"q": "wiki", "limit": 10, "skip": 20},
        ("GET", "/projects", {"params": {"q": "wiki", "limit": 10, "skip": 20}}),
    ),
    ("get_project", {"project_id": str(KB)}, ("GET", f"/projects/{KB}", {})),
    (
        "create_project",
        {"name": "Wiki"},
        (
            "POST",
            "/projects",
            {
                "json": {
                    "name": "Wiki",
                    "instructions": "",
                    "description": None,
                    "default_agent_id": None,
                    "visibility": "private",
                }
            },
        ),
    ),
    (
        "create_project",
        {
            "name": "Wiki",
            "instructions": "Read index.md first.",
            "description": "Continuing research",
            "default_agent_id": str(AGENT),
        },
        (
            "POST",
            "/projects",
            {
                "json": {
                    "name": "Wiki",
                    "instructions": "Read index.md first.",
                    "description": "Continuing research",
                    "default_agent_id": str(AGENT),
                    "visibility": "private",
                }
            },
        ),
    ),
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
                        "capabilities": [{"id": "ask_user"}, {"id": "drafts"}],
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
                        "capabilities": [{"id": "ask_user"}, {"id": "drafts"}],
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
                        "capabilities": [
                            {"id": "ask_user"},
                            {"id": "drafts"},
                            {"id": "web_research"},
                        ],
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
                        "capabilities": [{"id": "ask_user"}, {"id": "drafts"}],
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
            "time_zone": "Europe/Warsaw",
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
                    "time_zone": "Europe/Warsaw",
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
        "update_routine",
        {"agent_id": str(AGENT), "routine_id": str(RUN), "time_zone": "Asia/Tokyo"},
        (
            "PATCH",
            f"/agents/{AGENT}/triggers/{RUN}",
            {"json": {"time_zone": "Asia/Tokyo"}},
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
            {"params": {"limit": 100, "skip": 0, "for_model": True}},
        ),
    ),
    (
        "test_my_connection",
        {"connection_id": "00000000-0000-0000-0000-000000000002"},
        ("POST", "/me/mcp-connections/00000000-0000-0000-0000-000000000002/test", {}),
    ),
    (
        "list_conversations",
        {"search": "Geopolityka", "limit": 5},
        (
            "GET",
            "/conversations",
            {"params": {"limit": 5, "search": "Geopolityka", "for_model": True}},
        ),
    ),
    (
        "create_conversation",
        {"title": "GitHub daily"},
        ("POST", "/conversations", {"json": {"title": "GitHub daily"}}),
    ),
    (
        "update_proactivity_settings",
        {
            "watch_min_minutes": 20,
            "briefing_hour": 10,
            "monthly_limit_usd": "30",
            "briefing_enabled": True,
            "briefing_days": [1, 3],
        },
        (
            "PATCH",
            f"/orgs/{ORG}",
            {
                "json": {
                    "proactive_watch_min_minutes": 20,
                    "proactive_enabled": True,
                    "proactive_days": [1, 3],
                    "proactive_hour": 10,
                    "proactive_timing": "fixed",
                    "proactive_limit_usd": "30",
                }
            },
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


CALLS.extend(
    [
        (
            "run_workflow",
            {"workflow_id": str(AGENT)},
            (
                "POST",
                "/workflow-runs",
                {
                    "json": {
                        "workflow_id": str(AGENT),
                        "mode": "real",
                        "input": {},
                        "entry_node_id": None,
                    }
                },
            ),
        ),
        (
            "get_virtual_table_record",
            {"table_id": str(KB), "record_id": str(RUN)},
            ("GET", f"/tables/{KB}/records/{RUN}", {}),
        ),
        (
            "virtual_table_record_exists",
            {"table_id": str(KB), "external_id": "crm/1"},
            ("GET", f"/tables/{KB}/records/exists", {"params": {"external_id": "crm/1"}}),
        ),
        (
            "upsert_virtual_table_record",
            {
                "table_id": str(KB),
                "external_id": "crm/account.1",
                "record": {"values": {}, "expected_revision": 3},
            },
            (
                "PUT",
                f"/tables/{KB}/records/by-external-id/crm%2Faccount%2E1",
                {"json": {"values": {}, "expected_revision": 3}},
            ),
        ),
        (
            "delete_virtual_table_record",
            {"table_id": str(KB), "record_id": str(RUN), "expected_revision": 2},
            ("DELETE", f"/tables/{KB}/records/{RUN}", {"params": {"expected_revision": 2}}),
        ),
        (
            "list_virtual_table_views",
            {"table_id": str(KB)},
            ("GET", f"/tables/{KB}/views", {"params": {"limit": 50, "skip": 0}}),
        ),
    ]
)


CALLS.extend(
    [
        (
            "create_routine",
            {
                "agent_id": str(AGENT),
                "prompt": "Watch deployments",
                "every_minutes": 10,
                "ends_at": "2026-11-03T09:00:00+01:00",
                "monthly_budget_usd": "3.50",
                "delivery_conversation_id": str(RUN),
            },
            (
                "POST",
                f"/agents/{AGENT}/triggers",
                {
                    "json": {
                        "prompt": "Watch deployments",
                        "runs_as_creator": True,
                        "interval_seconds": 600,
                        "ends_at": "2026-11-03T09:00:00+01:00",
                        "monthly_budget_usd": "3.50",
                        "delivery_conversation_id": str(RUN),
                        "answer_to": "conversation",
                    }
                },
            ),
        ),
        (
            "update_routine",
            {
                "agent_id": str(AGENT),
                "routine_id": str(RUN),
                "clear_end": True,
                "clear_budget": True,
                "answer_to": "primary",
            },
            (
                "PATCH",
                f"/agents/{AGENT}/triggers/{RUN}",
                {"json": {"ends_at": None, "monthly_budget_usd": None, "answer_to": "primary"}},
            ),
        ),
    ]
)


CALLS.extend(
    [
        ("get_skill", {"skill_id": str(KB)}, ("GET", f"/skills/{KB}", {})),
        (
            "update_skill",
            {"skill_id": str(KB), "changes": {"content": "Revised"}},
            ("PATCH", f"/skills/{KB}", {"json": {"content": "Revised"}}),
        ),
        (
            "add_skill_resource",
            {"skill_id": str(KB), "resource": {"name": "example.md", "content": "Example"}},
            (
                "POST",
                f"/skills/{KB}/resources",
                {"json": {"name": "example.md", "content": "Example", "description": None}},
            ),
        ),
        (
            "list_context_files",
            {"q": "glossary"},
            ("GET", "/context", {"params": {"q": "glossary", "skip": 0, "limit": 50}}),
        ),
        ("get_context_file", {"context_id": str(KB)}, ("GET", f"/context/{KB}", {})),
        (
            "create_context_file",
            {"context": {"name": "glossary", "visibility": "private", "mode": "link"}},
            (
                "POST",
                "/context",
                {
                    "json": {
                        "name": "glossary",
                        "description": None,
                        "content": "",
                        "format": "md",
                        "mode": "link",
                        "visibility": "private",
                        "group_ids": [],
                        "user_ids": [],
                    }
                },
            ),
        ),
        (
            "update_context_file",
            {"context_id": str(KB), "changes": {"content": "Updated"}},
            ("PATCH", f"/context/{KB}", {"json": {"content": "Updated"}}),
        ),
    ]
)


@pytest.mark.parametrize(("tool", "arguments", "call"), CALLS)
async def test_each_tool_is_one_public_api_call(
    server: FastMCP, api: MagicMock, tool: str, arguments: dict[str, Any], call: tuple[Any, ...]
) -> None:
    if tool in ("list_projects", "list_conversations"):
        api.request.return_value = {"items": [], "total": 0}
    await server.call_tool(tool, arguments)

    method, path, kwargs = call
    assert api.request.await_args.args == (method, path)
    assert api.request.await_args.kwargs == kwargs


@pytest.mark.parametrize(
    "arguments",
    [
        {"ends_at": "2027-01-01T12:00:00+00:00", "clear_end": True},
        {"monthly_budget_usd": "5.00", "clear_budget": True},
        {"pinned_version_id": str(KB), "follow_latest": True},
    ],
)
async def test_routine_update_refuses_conflicting_limits(
    server: FastMCP, api: MagicMock, arguments: dict[str, object]
) -> None:
    with pytest.raises(ToolError, match="not both"):
        await server.call_tool(
            "update_routine", {"agent_id": str(AGENT), "routine_id": str(RUN), **arguments}
        )
    api.request.assert_not_awaited()


async def test_routine_update_sets_delivery_and_limits(server: FastMCP, api: MagicMock) -> None:
    await server.call_tool(
        "update_routine",
        {
            "agent_id": str(AGENT),
            "routine_id": str(RUN),
            "ends_at": "2027-01-01T12:00:00+00:00",
            "monthly_budget_usd": "5.00",
            "delivery_conversation_id": str(KB),
        },
    )
    api.request.assert_awaited_once_with(
        "PATCH",
        f"/agents/{AGENT}/triggers/{RUN}",
        json={
            "ends_at": "2027-01-01T12:00:00+00:00",
            "monthly_budget_usd": "5.00",
            "delivery_conversation_id": str(KB),
            "answer_to": "conversation",
        },
    )


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
                "name": "Renamed Bot",
                "description": "Answers refunds",
                "add_capabilities": ["knowledge", "clock", "knowledge"],
                "remove_capabilities": ["ask_user"],
                "model_profile_id": str(KB),
                "skill_ids": [str(skill)],
                "collection_ids": [str(KB)],
                "context_ids": [str(KB)],
                "starters": ["How do refunds work?"],
            },
        )

        read, write = api.request.await_args_list
        assert read.args == ("GET", f"/agents/{AGENT}")
        assert write.args == ("PUT", f"/agents/{AGENT}/draft")
        assert write.kwargs["json"]["spec"] == {
            "name": "Renamed Bot",
            "instructions": "New",
            "description": "Answers refunds",
            "model_profile_id": str(KB),
            # A binding already there keeps its config; a new one takes defaults.
            "capabilities": [{"id": "clock", "config": {"timezone": "UTC"}}, {"id": "knowledge"}],
            "skill_ids": [str(skill)],
            "collection_ids": [str(KB)],
            "context_ids": [str(KB)],
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
    @pytest.mark.security
    def test_only_console_language_bypasses_write_approval(self) -> None:
        """Persistent automation requires the configured write confirmation."""
        tools = {tool.name: tool for tool in platform_tool_catalog()}

        assert {name for name, tool in tools.items() if tool.ungated} == {"set_my_language"}
        for name in ("create_routine", "update_routine", "create_watch", "update_watch"):
            assert tools[name].writes and not tools[name].ungated
        assert tools["set_my_language"].writes

    @pytest.mark.security
    def test_saving_the_profile_every_agent_is_told_waits_for_approval(self) -> None:
        """Codex on #2324: what it saves is appended to every agent's instructions,
        so a page that injected the call would otherwise persist into later runs."""
        tools = {tool.name: tool for tool in platform_tool_catalog()}

        assert tools["set_my_profile"].writes
        assert not tools["set_my_profile"].ungated
        assert tools["create_project"].writes and not tools["create_project"].ungated
        assert not tools["list_projects"].writes
        assert not tools["get_project"].writes
        assert tools["create_skill"].writes and not tools["create_skill"].ungated
        assert tools["publish_agent"].writes and not tools["publish_agent"].ungated
        assert tools["test_my_connection"].writes and not tools["test_my_connection"].ungated

    @pytest.mark.security
    async def test_reads_run_under_writes_but_all_still_requires_approval(self) -> None:
        from pydantic_ai.tools import ToolDefinition

        from app.agents.mcp import needs_approval
        from app.services.platform_mcp import build_platform_mcp

        server, _ = build_platform_mcp(MagicMock())
        listed = {tool.name: tool for tool in await server.list_tools()}
        for declared in platform_tool_catalog():
            tool = listed[declared.name]
            assert tool.annotations.read_only_hint is (not declared.writes)
            definition = ToolDefinition(
                name=tool.name,
                metadata={"annotations": tool.annotations.model_dump(by_alias=True)},
            )
            assert needs_approval(definition, "writes") is declared.writes
            assert needs_approval(definition, "all") is True
        for name in ("get_project", "read_conversation", "get_run"):
            assert listed[name].annotations.read_only_hint is True

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

        with pytest.raises(ToolError, match="Insufficient permissions"):
            await _api(handler).request("POST", "/agents", json={})

    async def test_an_unexpected_error_body_still_says_something(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, json=["not", "an", "envelope"])

        with pytest.raises(ToolError, match="The platform request failed"):
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
            {"id": "drafts"},
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


@pytest.mark.security
async def test_project_discovery_returns_only_names_and_ids(
    server: FastMCP, api: MagicMock
) -> None:
    api.request.return_value = {
        "items": [
            {
                "id": str(KB),
                "name": "Shared wiki",
                "instructions": "Untrusted payload",
                "description": "Injected description",
                "default_agent_name": "Another label",
            }
        ],
        "total": 12,
        "skip": 0,
        "limit": 1,
    }
    listing = await server.call_tool("list_projects", {"limit": 1})
    assert listing.structured_content == {
        "items": [{"id": str(KB), "name": "Shared wiki"}],
        "total": 12,
        "skip": 0,
        "limit": 1,
    }


async def test_project_discovery_preserves_empty_pages(server: FastMCP, api: MagicMock) -> None:
    api.request.return_value = {"items": [], "total": 0}
    assert (await server.call_tool("list_projects", {})).structured_content == {
        "items": [],
        "total": 0,
    }


async def test_create_project_configures_only_the_shared_workspace(api: MagicMock) -> None:
    tool = next(tool for tool in platform_tools(api) if tool.name == "create_project")
    await tool.function(name="Local coding", backend="service", sandbox_connection_id=KB)
    payload = api.request.call_args.kwargs["json"]
    assert payload["backend"] == "service"
    assert payload["sandbox_connection_id"] == str(KB)
    assert "local" not in payload and "folder" not in payload
    assert tool.writes
    assert "cannot select a native folder" in tool.function.__doc__


async def test_table_deletion_reports_success_only_after_confirmed_204(api):
    tool = next(tool for tool in platform_tools(api) if tool.name == "delete_virtual_table_record")
    api.request.return_value = None
    assert await tool.function(KB, RUN, 2) == {"deleted": True}
    api.request.return_value = {"error": "revision conflict"}
    assert await tool.function(KB, RUN, 2) == {"error": "revision conflict"}


@pytest.mark.security
async def test_a_workflow_agent_cannot_start_a_new_root_through_platform_mcp(api):
    from app.core.permissions import AuthContext
    from app.services.workflow_execution import context

    dispatch = context.DispatchContext(
        organization_id=uuid.UUID(ORG),
        workflow_run_id=RUN,
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=AGENT, organization_id=uuid.UUID(ORG), role="owner"),
        resumed_agent_run_id=None,
    )
    tool = next(tool for tool in platform_tools(api) if tool.name == "run_workflow")
    api.refuse.return_value = {"error": "use workflow.run"}
    with context.dispatching_as(dispatch):
        assert await tool.function(AGENT) == {"error": "use workflow.run"}
    api.request.assert_not_awaited()
    api.refuse.assert_called_once()


@pytest.mark.security
def test_workflow_and_table_mcp_writes_wait_for_approval():
    tools = {tool.name: tool for tool in platform_tool_catalog()}
    assert all(
        tools[name].writes
        for name in ["run_workflow", "upsert_virtual_table_record", "delete_virtual_table_record"]
    )
    assert not tools["get_virtual_table_record"].writes


async def test_domain_errors_retain_safe_fields_in_the_recorded_tool_answer():
    from app.services.platform_mcp import _tool_error

    api = PlatformApi(MagicMock(), token=lambda: "test", on_refusal=_tool_error)
    api._transport = httpx.MockTransport(
        lambda request: httpx.Response(
            422,
            json={
                "error": {
                    "code": "INVALID_SCHEMA",
                    "message": "Invalid column",
                    "details": {
                        "fields": [{"field": "columns.0.default", "message": "Needs a default"}]
                    },
                }
            },
        )
    )
    from app.services.platform_mcp import _with_domain_errors

    async def call():
        return await api.request("POST", "/tables")

    result = await _with_domain_errors(call)()
    assert result.is_error
    assert result.structured_content["error"]["code"] == "INVALID_SCHEMA"
    assert (
        result.structured_content["error"]["details"]["fields"][0]["field"] == "columns.0.default"
    )


async def test_unexpected_platform_failures_stay_masked():
    from fastmcp import Client

    from app.services.platform_mcp import _with_domain_errors

    server = FastMCP("test", mask_error_details=True)

    async def broken() -> dict[str, object]:
        raise RuntimeError("confidential internal detail")

    server.tool(_with_domain_errors(broken))
    async with Client(server) as client:
        result = await client.call_tool("broken", {}, raise_on_error=False)
    assert result.is_error
    assert "confidential" not in str(result.content)


@pytest.mark.parametrize("follow_latest", [False, True])
async def test_routine_update_selects_version_policy(
    server: FastMCP, api: MagicMock, follow_latest: bool
) -> None:
    arguments = {"follow_latest": True} if follow_latest else {"pinned_version_id": str(KB)}
    await server.call_tool(
        "update_routine",
        {
            "agent_id": str(AGENT),
            "routine_id": str(RUN),
            **arguments,
        },
    )
    assert api.request.await_args.kwargs["json"] == {
        "pinned_version_id": None if follow_latest else str(KB),
        "environment_id": None,
    }


async def test_routine_creation_can_pin_a_published_version(
    server: FastMCP, api: MagicMock
) -> None:
    await server.call_tool(
        "create_routine",
        {
            "agent_id": str(AGENT),
            "prompt": "Report",
            "every_minutes": 60,
            "pinned_version_id": str(KB),
        },
    )
    assert api.request.await_args.kwargs["json"]["pinned_version_id"] == str(KB)


@pytest.mark.parametrize(
    "conflict",
    [
        {"clear_pin": True, "pinned_version_id": KB},
        {"clear_end": True, "ends_at": "2026-12-01T08:00:00Z"},
    ],
)
async def test_a_watch_limit_cannot_be_cleared_and_set_in_the_same_tool_request(api, conflict):
    tool = {tool.name: tool for tool in platform_tools(api)}["update_watch"]
    with pytest.raises(ValueError, match="set and cleared"):
        await tool.function(watch_id=RUN, **conflict)
    api.request.assert_not_awaited()


@pytest.mark.security
async def test_delete_watch_uses_the_same_identity_and_requires_approval(api):
    tool = {tool.name: tool for tool in platform_tools(api)}["delete_watch"]
    assert await tool.function(watch_id=RUN) == {"deleted": str(RUN)}
    api.request.assert_awaited_once_with("DELETE", f"/me/watches/{RUN}")
    definition = {tool.name: tool for tool in platform_tool_catalog()}["delete_watch"]
    assert definition.writes and not definition.ungated


async def test_turkish_console_switch_uses_the_askers_own_account(
    server: FastMCP, api: MagicMock
) -> None:
    api.request.return_value = {"locale": "tr"}
    result = await server.call_tool("set_my_language", {"locale": "tr"})
    api.request.assert_awaited_once_with("PUT", "/users/me/locale", json={"locale": "tr"})
    assert result.structured_content == {"locale": "tr"}


async def test_an_unsupported_console_language_is_refused_before_any_api_call(
    server: FastMCP, api: MagicMock
) -> None:
    with pytest.raises(MCPValidationError):
        await server.call_tool("set_my_language", {"locale": "xx"})
    api.request.assert_not_called()


async def test_mcp_can_find_and_settle_the_callers_working_case(api):
    tools = {tool.name: tool.function for tool in platform_tools(api)}
    await tools["list_inbox_cases"](conversation_id=RUN)
    api.request.assert_awaited_with(
        "GET", "/outcomes", params={"include_source": "true", "conversation_id": str(RUN)}
    )
    await tools["settle_inbox_case"](outcome_id=RUN, action="resolve")
    api.request.assert_awaited_with(
        "POST", f"/outcomes/{RUN}/settle", json={"action": "resolve", "via": "chat"}
    )


async def test_mcp_routine_result_policy_is_preserved_on_create_and_update(api):
    tools = {tool.name: tool.function for tool in platform_tools(api)}
    await tools["create_routine"](
        agent_id=AGENT, prompt="Check mail and draft replies", every_minutes=60, result_mode="inbox"
    )
    assert api.request.await_args.kwargs["json"]["result_mode"] == "inbox"
    await tools["update_routine"](agent_id=AGENT, routine_id=RUN, result_mode="report")
    assert api.request.await_args.kwargs["json"] == {"result_mode": "report"}


async def test_answering_a_draft_question_uses_the_owned_run_answer_endpoint(
    server: FastMCP, api: MagicMock
) -> None:
    await server.call_tool(
        "answer_agent_questions",
        {
            "run_id": str(RUN),
            "answers": {
                "responses": {
                    "question-call": [{"selected": ["Ray"], "answer": "", "skipped": False}]
                }
            },
        },
    )
    assert api.request.await_args.args == ("POST", f"/runs/{RUN}/answers")
    assert api.request.await_args.kwargs["json"] == {
        "responses": {"question-call": [{"selected": ["Ray"], "answer": "", "skipped": False}]}
    }


async def test_task_receipts_and_unfiltered_context_use_the_current_api(server, api):
    await server.call_tool("get_task", {"task_id": str(RUN)})
    assert api.request.await_args.args == ("GET", f"/tasks/{RUN}")
    await server.call_tool("list_context_files", {})
    assert api.request.await_args.kwargs == {"params": {"limit": 50, "skip": 0}}
    await server.call_tool(
        "create_routine", {"agent_id": str(AGENT), "prompt": "Check", "answer_to": "primary"}
    )
    assert api.request.await_args.kwargs["json"]["answer_to"] == "primary"


@pytest.mark.security
async def test_routine_notification_override_and_inheritance_are_mutually_exclusive(server, api):
    with pytest.raises(ToolError, match="not both"):
        await server.call_tool(
            "update_routine",
            {
                "agent_id": str(AGENT),
                "routine_id": str(RUN),
                "inherit_notifications": True,
                "notification_channels": [],
            },
        )
    api.request.assert_not_awaited()


async def test_proactivity_settings_need_something_to_change(server: FastMCP, api: MagicMock):
    with pytest.raises(Exception, match="at least one setting"):
        await server.call_tool("update_proactivity_settings", {})
    api.request.assert_not_called()


async def test_proactivity_settings_need_an_organization(api: MagicMock):
    api.request.return_value = {}
    tools = {tool.name: tool.function for tool in platform_tools(api)}
    with pytest.raises(ValueError, match="names no organization"):
        await tools["update_proactivity_settings"](watches_enabled=True)


async def test_a_conversation_listing_carries_only_ids_titles_and_dates(api: MagicMock):
    api.request.return_value = {
        "total": 1,
        "items": [{"id": "c1", "title": "Plan", "created_at": "t", "updated_at": "u", "x": 1}],
    }
    tools = {tool.name: tool.function for tool in platform_tools(api)}
    assert await tools["list_conversations"]() == {
        "total": 1,
        "items": [{"id": "c1", "title": "Plan", "created_at": "t", "updated_at": "u"}],
    }


async def test_a_connection_check_names_its_tools(api: MagicMock):
    api.request.return_value = {"ok": True, "error": None, "tools": [{"name": "search"}]}
    tools = {tool.name: tool.function for tool in platform_tools(api)}
    assert await tools["test_my_connection"](connection_id=uuid.uuid4()) == {
        "ok": True,
        "error": None,
        "tools": ["search"],
    }


def test_proactivity_tool_explains_both_required_scopes(api: MagicMock) -> None:
    tool = next(tool for tool in platform_tools(api) if tool.name == "update_proactivity_settings")
    assert tool.function.__doc__ is not None
    assert "`org:settings` and `budgets:manage`" in tool.function.__doc__
