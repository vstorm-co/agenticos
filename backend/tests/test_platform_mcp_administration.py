"""Administrative discovery is small; read and write dispatch cannot cross their contracts."""

import re
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastmcp.exceptions import ToolError

from app.services.platform_mcp._administration import (
    ACTION_CATALOG,
    _action,
    _path,
    administration_operations,
)

pytestmark = pytest.mark.anyio
ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def api() -> MagicMock:
    client = MagicMock()
    client.request = AsyncMock(return_value={"id": ID})
    return client


def functions(api: MagicMock) -> dict[str, Callable[..., Awaitable[object]]]:
    return {name: function for name, function, _ in administration_operations(api)}


def test_catalog_is_explicit_and_every_write_has_a_read_back_contract() -> None:
    identities = {action.id for action in ACTION_CATALOG}
    assert len(identities) == len(ACTION_CATALOG)
    for action in ACTION_CATALOG:
        if action.writes:
            assert action.read_action in identities and not _action(action.read_action).writes
        else:
            assert action.method == "GET"
        assert not action.path.startswith("http")


async def test_searches_model_fields_before_paging_without_loading_settings(api: MagicMock) -> None:
    tools = functions(api)
    result = await tools["list_administration_actions"](
        q="maintenance mode", area="deployment", limit=1
    )
    assert result["items"][0]["id"] == "deployment.settings.update"
    assert result["items"][0]["execution"] == "change_deployment"
    assert (await tools["list_administration_actions"](area="organization", limit=1))[
        "next_skip"
    ] == 1
    assert (await tools["list_administration_actions"](q="does-not-exist"))["total"] == 0
    all_actions = await tools["list_administration_actions"](limit=50)
    assert any(item["execution"] == "console_handoff" for item in all_actions["items"])
    api.request.assert_not_awaited()


async def test_schema_discovery_keeps_body_refs_rooted_and_requires_exact_path_parameters(
    api: MagicMock,
) -> None:
    read = functions(api)["get_administration_schema"]
    body = await read("organization.settings.update", pointer="/body/properties/name")
    assert body["total"] > 0
    assert (await read("organization.settings.update", pointer="/body/type", mode="content"))[
        "content"
    ] == "object"
    assert (await read("organization.members.remove", pointer="/body/maxProperties"))["value"] == 0
    paths = await read("organization.members.remove", pointer="/path", mode="content")
    assert "target_user_id" in paths["content"]


@pytest.mark.security
@pytest.mark.parametrize(
    "action,parameters",
    [
        ("organization.settings.read", {}),
        ("deployment.settings.read", {"org_id": ID}),
        ("organization.settings.read", {"org_id": "../../admin/settings"}),
        ("organization.system_agents.update", {"role": "../../settings"}),
    ],
)
def test_path_values_cannot_select_another_route(action: str, parameters: dict[str, str]) -> None:
    with pytest.raises(ToolError):
        _path(_action(action), parameters)


def test_role_paths_use_only_supported_system_roles() -> None:
    assert (
        _path(_action("organization.system_agents.update"), {"role": "memory_maintenance"})
        == "/system-agents/memory_maintenance"
    )
    assert _path(_action("organization.settings.read"), {"org_id": ID}) == f"/orgs/{ID}"
    with pytest.raises(ToolError, match="Unknown"):
        _action("https://other-host/admin/settings")


@pytest.mark.security
async def test_read_dispatch_never_executes_writes_or_installs(api: MagicMock) -> None:
    read = functions(api)["read_administration"]
    for action in [
        "deployment.settings.update",
        "organization.assistant.install",
        "organization.groups.remove",
    ]:
        with pytest.raises(ToolError, match="changes state"):
            await read(action)
    api.request.assert_not_awaited()


async def test_server_pages_search_in_sql_and_project_metadata(api: MagicMock) -> None:
    api.request.return_value = {
        "items": [{"id": ID, "name": "Team", "content": "large"}],
        "total": 9,
    }
    read = functions(api)["read_administration"]
    result = await read(
        "deployment.organizations.list", q="Team", filters={"kind": "team"}, limit=1, skip=3
    )
    assert result["items"] == [{"id": ID, "name": "Team"}]
    assert result["next_skip"] == 4 and result["total"] == 9
    api.request.assert_awaited_with(
        "GET",
        "/admin/organizations",
        params={"kind": "team", "limit": 1, "skip": 3, "search": "Team"},
    )
    with pytest.raises(ToolError, match="query"):
        await read("deployment.organizations.list", filters={"arbitrary": "query"})


async def test_unpaged_groups_are_searched_before_local_paging_and_detail_is_explicit(
    api: MagicMock,
) -> None:
    api.request.return_value = {
        "items": [
            {"id": ID, "name": "Team", "description": "body"},
            {"id": "other", "name": "Another"},
        ]
    }
    read = functions(api)["read_administration"]
    result = await read(
        "organization.groups.list", parameters={"org_id": ID}, q="Team", detailed=True
    )
    assert result["total"] == 1 and result["items"][0]["description"] == "body"
    api.request.assert_awaited_with("GET", f"/orgs/{ID}/groups", params=None)
    api.request.return_value = {"app_name": "Installation"}
    assert (await read("deployment.settings.read"))["app_name"] == "Installation"
    with pytest.raises(ToolError, match="no search"):
        await read("deployment.settings.read", q="Installation")


@pytest.mark.security
async def test_credentials_and_binary_assets_have_small_user_handoffs(api: MagicMock) -> None:
    read = functions(api)["read_administration"]
    for identity in ("deployment.apns.configure", "deployment.branding.upload"):
        result = await read(identity)
        assert (
            result["user_action_required"] is True and "/admin/settings?section=" in result["url"]
        )
    api.request.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    "tool,action",
    [
        ("change_deployment", "organization.settings.update"),
        ("change_organization", "deployment.settings.update"),
        ("change_deployment", "deployment.settings.read"),
        ("change_deployment", "deployment.apns.configure"),
    ],
)
async def test_change_dispatch_is_fixed_to_its_administration_area(
    api: MagicMock, tool: str, action: str
) -> None:
    with pytest.raises(ToolError, match="write action"):
        await functions(api)[tool](action)
    api.request.assert_not_awaited()


@pytest.mark.security
async def test_updates_validate_complete_typed_inputs_and_preserve_omitted_fields(
    api: MagicMock,
) -> None:
    change = functions(api)["change_organization"]
    result = await change(
        "organization.members.update",
        parameters={"org_id": ID, "target_user_id": ID},
        changes={"role": "member"},
    )
    api.request.assert_awaited_with("PATCH", f"/orgs/{ID}/members/{ID}", json={"role": "member"})
    assert result["parameters"] == {"org_id": ID}
    assert result["read_action"] == "organization.members.list"
    with pytest.raises(ToolError) as error:
        await change(
            "organization.members.update",
            parameters={"org_id": ID, "target_user_id": ID},
            changes={"role": "invented", "password": "never-echo-this"},
        )
    assert "never-echo-this" not in str(error.value)
    assert api.request.await_count == 1


async def test_bodyless_changes_and_large_write_results_keep_a_receipt(api: MagicMock) -> None:
    change = functions(api)["change_deployment"]
    api.request.return_value = {"app_name": "Updated", "content": "x" * 50000}
    result = await change("deployment.logo.clear")
    api.request.assert_awaited_with("DELETE", "/admin/settings/logo", json=None)
    assert result["result"] == {"app_name": "Updated"}
    assert result["request_completed"] and result["read_action"] == "deployment.settings.read"
    with pytest.raises(ToolError, match="no body"):
        await change("deployment.logo.clear", changes={"unexpected": True})


def test_action_routes_are_actual_public_or_assistant_api_operations() -> None:
    from app.api.public_api import assistant_operations, public_operations
    from app.core.config import settings
    from app.main import app

    operations = assistant_operations(app.routes) | public_operations(app.routes)
    for action in ACTION_CATALOG:
        if action.handoff:
            continue
        names = re.findall(r"{([a-z_]+)}", action.path)
        path = _path(
            action, {key: "memory_maintenance" if key == "role" else str(UUID(ID)) for key in names}
        )
        assert any(
            verb == action.method.lower()
            and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), settings.API_V1_STR + path)
            for verb, template in operations
        ), action.id
