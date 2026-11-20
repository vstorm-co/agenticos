"""Read-only Composio catalog boundary tests."""

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConfigurationError, ExternalServiceError
from app.services.app_connections._catalog import (
    APPS,
    ComposioAction,
    get_app,
    resolve_action,
    toolkit_from_catalog_key,
)
from app.services.app_connections._client import ComposioCatalogClient
from app.services.app_connections._managed import (
    is_managed_auth_type,
    is_managed_catalog_key,
)

pytestmark = pytest.mark.anyio

CATALOG_KEY = "synthetic-catalog-secret"
RUNTIME_KEY = "synthetic-runtime-secret"


@pytest.fixture(autouse=True)
def provider_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "COMPOSIO_API_KEY", SecretStr(RUNTIME_KEY))
    monkeypatch.setattr(settings, "COMPOSIO_CATALOG_API_KEY", SecretStr(CATALOG_KEY))


def toolkit_row() -> dict[str, object]:
    return {
        "slug": "microsoft_teams",
        "name": "Microsoft Teams",
        "no_auth": False,
        "deprecated": {
            "toolkitId": "microsoft_teams",
            "getCurrentUserEndpoint": "/me",
            "rawProxyInfoByAuthSchemes": [{"auth_scheme": "OAUTH2"}],
        },
        "enabled": True,
        "composio_managed_auth_schemes": ["OAUTH2"],
        "composio_managed_auth": [
            {"mode": "OAUTH2", "scopes": {"available": ["admin", "read", "write"]}}
        ],
        "meta": {
            "description": "Manage channels and messages.",
            "categories": [{"slug": "productivity", "name": "Productivity"}],
            "tools_count": 42,
        },
        # The provider may return extra fields. They must not cross this metadata boundary.
        "access_token": "catalog-response-token-must-not-escape",
    }


def direct_tool(
    slug: str,
    toolkit: str = "microsoft_teams",
    *,
    deprecated: bool = False,
    legacy_deprecated: bool = False,
) -> dict[str, object]:
    return {
        "slug": slug,
        "toolkit": {"slug": toolkit, "logo": "https://example.test/toolkit.svg"},
        "deprecated": {
            "displayName": "Archive issue",
            "version": "20261101_00",
            "available_versions": ["20261101_00"],
            "is_deprecated": legacy_deprecated,
        },
        "is_deprecated": deprecated,
    }


@pytest.mark.parametrize("key", [None, SecretStr(""), SecretStr("   ")])
def test_catalog_requires_its_separate_nonempty_credential(
    monkeypatch: pytest.MonkeyPatch, key: SecretStr | None
) -> None:
    monkeypatch.setattr(settings, "COMPOSIO_CATALOG_API_KEY", key)
    with pytest.raises(ConfigurationError, match="COMPOSIO_CATALOG_API_KEY"):
        ComposioCatalogClient()


async def test_toolkit_listing_uses_fixed_origin_catalog_key_and_paging_params() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert (
            str(request.url.copy_with(query=None))
            == "https://backend.composio.dev/api/v3.1/toolkits"
        )
        assert dict(request.url.params) == {
            "type": "native",
            "include_deprecated": "false",
            "sort_by": "usage",
            "limit": "24",
            "search": "calendar events",
            "cursor": "page_2",
        }
        assert request.headers["x-api-key"] == CATALOG_KEY
        assert RUNTIME_KEY not in str(request.headers)
        assert request.content == b""
        return httpx.Response(200, json={"items": [toolkit_row()], "next_cursor": "page_3"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        page = await ComposioCatalogClient(http).list_toolkits(
            search="  calendar events  ", cursor="page_2", limit=24
        )

    assert len(requests) == 1
    assert page.next_cursor == "page_3"
    item = page.items[0]
    assert item.slug == "microsoft_teams"
    assert item.has_managed_auth
    assert item.action_count == 42
    assert item.summary == "Manage channels and messages."
    assert item.category_name == "Productivity"
    serialized = page.model_dump_json()
    assert "catalog-response-token-must-not-escape" not in serialized
    assert "getCurrentUserEndpoint" not in serialized
    assert "rawProxyInfoByAuthSchemes" not in serialized


async def test_toolkit_detail_accepts_live_metadata_and_ignores_legacy_compatibility_fields() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url.copy_with(query=None)) == (
            "https://backend.composio.dev/api/v3.1/toolkits/microsoft_teams"
        )
        assert dict(request.url.params) == {"version": "latest"}
        assert request.headers["x-api-key"] == CATALOG_KEY
        return httpx.Response(
            200,
            json={
                "slug": "microsoft_teams",
                "name": "Microsoft Teams",
                "description": "Manage channels and messages.",
                "categories": [{"slug": "productivity", "name": "Productivity"}],
                "tools_count": 42,
                "deprecated": {
                    "toolkitId": "microsoft_teams",
                    "getCurrentUserEndpoint": "/me",
                    "rawProxyInfoByAuthSchemes": [{"auth_scheme": "OAUTH2"}],
                },
                "enabled": True,
                "composio_managed_auth_schemes": ["OAUTH2"],
                "composio_managed_auth": [
                    {"mode": "OAUTH2", "scopes": {"available": ["admin", "read", "write"]}}
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        metadata = await ComposioCatalogClient(http).get_toolkit("microsoft_teams")

    assert metadata.slug == "microsoft_teams"
    assert metadata.no_auth is False
    assert metadata.has_managed_auth
    assert metadata.composio_managed_auth_schemes == ["OAUTH2"]
    assert metadata.composio_managed_auth == [
        {"mode": "OAUTH2", "scopes": {"available": ["admin", "read", "write"]}}
    ]
    assert metadata.is_deprecated_flag is False
    assert metadata.action_count == 42
    assert metadata.summary == "Manage channels and messages."
    assert metadata.category_name == "Productivity"
    serialized = metadata.model_dump_json()
    assert "getCurrentUserEndpoint" not in serialized
    assert "rawProxyInfoByAuthSchemes" not in serialized


async def test_invalid_toolkit_identifier_is_refused_before_provider_request() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("must not call provider"))
    ) as http:
        with pytest.raises(ExternalServiceError, match="identifier"):
            await ComposioCatalogClient(http).get_toolkit("microsoft_teams/../../other")


async def test_direct_actions_keep_underscores_and_use_actual_deprecation_flags() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert (
            str(request.url.copy_with(query=None)) == "https://backend.composio.dev/api/v3.1/tools"
        )
        assert dict(request.url.params) == {
            "toolkit_slug": "microsoft_teams",
            "toolkit_versions": "latest",
            "include_deprecated": "false",
            "limit": "1000",
        }
        assert request.headers["x-api-key"] == CATALOG_KEY
        return httpx.Response(
            200,
            json={
                "items": [
                    direct_tool("MICROSOFT_TEAMS_LIST_MESSAGES"),
                    direct_tool("MICROSOFT_TEAMS_SEND_MESSAGE"),
                    direct_tool("MICROSOFT_TEAMS_SEND_MESSAGE"),
                    direct_tool("MICROSOFT_TEAMS_DELETE_MESSAGE", deprecated=True),
                    direct_tool("MICROSOFT_TEAMS_ARCHIVE_CHANNEL", legacy_deprecated=True),
                    direct_tool("COMPOSIO_SEARCH_TOOLS"),
                    direct_tool("GMAIL_SEARCH_EMAILS", toolkit="gmail"),
                    direct_tool("INVALID/TOOL"),
                ],
                "next_cursor": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        names = await ComposioCatalogClient(http).direct_tool_names(toolkit="microsoft_teams")

    assert names == ["MICROSOFT_TEAMS_LIST_MESSAGES", "MICROSOFT_TEAMS_SEND_MESSAGE"]


async def test_direct_actions_refuse_results_that_exceed_the_bounded_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3.1/tools"
        assert request.url.params["limit"] == "1000"
        return httpx.Response(
            200,
            json={
                "items": [direct_tool(f"MICROSOFT_TEAMS_TOOL_{index}") for index in range(1001)],
                "next_cursor": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ExternalServiceError, match="operator setup"):
            await ComposioCatalogClient(http).direct_tool_names(toolkit="microsoft_teams")


async def test_direct_actions_refuse_a_paged_result_instead_of_silently_truncating() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["limit"] == "1000"
        return httpx.Response(
            200,
            json={"items": [direct_tool("MICROSOFT_TEAMS_LIST_MESSAGES")], "next_cursor": "next"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ExternalServiceError, match="operator setup"):
            await ComposioCatalogClient(http).direct_tool_names(toolkit="microsoft_teams")


@pytest.mark.parametrize("status", [302, 500])
async def test_catalog_provider_failures_do_not_follow_redirects_or_leak_credentials(
    status: int,
) -> None:
    requests: list[httpx.Request] = []
    body = f"upstream failure mentions {CATALOG_KEY} and {RUNTIME_KEY}"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "backend.composio.dev"
        assert request.headers["x-api-key"] == CATALOG_KEY
        return httpx.Response(
            status, text=body, headers={"location": "https://evil.example/catalog"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as http:
        with pytest.raises(ExternalServiceError) as caught:
            await ComposioCatalogClient(http).list_toolkits(search="", cursor=None, limit=24)

    assert len(requests) == 1
    assert body not in str(caught.value)
    assert CATALOG_KEY not in repr(caught.value)
    assert RUNTIME_KEY not in repr(caught.value)


async def test_missing_toolkit_and_malformed_catalog_response_are_safe_failures() -> None:
    provider_secret = "provider-private-response"
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if request.url.path.endswith("/missing_toolkit"):
            return httpx.Response(404, text=f"{provider_secret}: missing")
        return httpx.Response(200, text=f"not-json {provider_secret}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = ComposioCatalogClient(http)
        with pytest.raises(ExternalServiceError) as missing:
            await catalog.get_toolkit("missing_toolkit")
        with pytest.raises(ExternalServiceError, match="invalid catalog response") as malformed:
            await catalog.list_toolkits(search="", cursor=None, limit=24)

    assert requests == 2
    assert provider_secret not in str(missing.value)
    assert provider_secret not in str(malformed.value)
    assert CATALOG_KEY not in repr(missing.value)
    assert CATALOG_KEY not in repr(malformed.value)


def test_managed_registry_names_only_the_vendor() -> None:
    assert is_managed_auth_type("composio")
    assert not is_managed_auth_type("oauth")
    assert not is_managed_auth_type("bearer")
    assert not is_managed_auth_type(None)
    assert is_managed_catalog_key("composio-gmail")
    assert is_managed_catalog_key("COMPOSIO-GMAIL")
    assert not is_managed_catalog_key("gmail")
    assert not is_managed_catalog_key(None)


def test_side_effecting_is_the_provider_neutral_read_of_read_only() -> None:
    assert ComposioAction("GMAIL_FETCH_EMAILS", "Find email").side_effecting is False
    assert (
        ComposioAction("GMAIL_SEND_MESSAGE", "Send email", read_only=False).side_effecting is True
    )


def test_resolve_action_returns_the_composio_executor() -> None:
    action = get_app("gmail").actions[0]
    executor = resolve_action(action)
    assert executor.kind == "composio"
    assert executor.tool_name == "GMAIL_FETCH_EMAILS"
    assert executor.side_effecting is False
    assert executor.scopes == ("https://www.googleapis.com/auth/gmail.readonly",)


def test_starter_actions_carry_least_privilege_scopes() -> None:
    by_toolkit = {app.toolkit: app for app in APPS}
    assert len(by_toolkit) == 7
    for app in APPS:
        assert all(not action.side_effecting for action in app.actions)
        assert all(action.read_only for action in app.actions)
    gmail = by_toolkit["gmail"]
    assert all(
        action.scopes == ("https://www.googleapis.com/auth/gmail.readonly",)
        for action in gmail.actions
    )
    drive = by_toolkit["googledrive"]
    assert all(
        action.scopes == ("https://www.googleapis.com/auth/drive.readonly",)
        for action in drive.actions
    )
    calendar = by_toolkit["googlecalendar"]
    assert all(
        action.scopes == ("https://www.googleapis.com/auth/calendar.readonly",)
        for action in calendar.actions
    )
    outlook = by_toolkit["outlook"]
    assert outlook.actions[0].scopes == ("Mail.Read",)
    assert outlook.actions[1].scopes == ("Mail.Read",)
    assert outlook.actions[2].scopes == ("Calendars.Read",)
    slack = by_toolkit["slack"]
    assert slack.actions[0].scopes == ("search:read",)
    assert "channels:history" in slack.actions[1].scopes
    assert "channels:history" in slack.actions[2].scopes
    notion = by_toolkit["notion"]
    assert all(action.scopes == () for action in notion.actions)
    github = by_toolkit["github"]
    assert all(action.scopes == ("repo",) for action in github.actions)


@pytest.mark.security
def test_catalog_key_parsing_does_not_admit_an_unreviewed_public_binding() -> None:
    assert get_app("github").toolkit == "github"
    assert toolkit_from_catalog_key(None) is None
    assert toolkit_from_catalog_key("gmail") is None
    assert toolkit_from_catalog_key("composio-salesforce") == "salesforce"
    with pytest.raises(BadRequestError, match="not available"):
        get_app("salesforce")


async def test_unknown_legacy_deprecation_metadata_does_not_replace_explicit_flags() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            tool = direct_tool("MICROSOFT_TEAMS_LIST_CHANNELS")
            tool["deprecated"] = "legacy-description"
            return httpx.Response(200, json={"items": [tool]})
        metadata = toolkit_row()
        metadata["deprecated"] = "legacy-description"
        return httpx.Response(200, json=metadata)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = ComposioCatalogClient(http)
        metadata = await catalog.get_toolkit("microsoft_teams")
        assert metadata.deprecated is None and not metadata.is_deprecated_flag
        assert await catalog.direct_tool_names(toolkit="microsoft_teams") == [
            "MICROSOFT_TEAMS_LIST_CHANNELS"
        ]


async def test_catalog_context_closes_only_the_http_client_it_owns() -> None:
    owned = ComposioCatalogClient()
    async with owned as entered:
        assert entered is owned and not owned._client.is_closed
    assert owned._client.is_closed
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("No provider request expected"))
    ) as http:
        async with ComposioCatalogClient(http) as injected:
            assert injected._client is http
        assert not http.is_closed


@pytest.mark.security
async def test_catalog_network_failure_does_not_reveal_credentials_or_retry() -> None:
    calls: list[httpx.Request] = []
    private = "synthetic-private-transport-detail"

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout(private, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ExternalServiceError) as caught:
            await ComposioCatalogClient(http).list_toolkits(search="", cursor=None, limit=24)
    assert len(calls) == 1
    for secret in (private, CATALOG_KEY, RUNTIME_KEY):
        assert secret not in str(caught.value) and secret not in repr(caught.value)


@pytest.mark.parametrize("limit", [0, 101])
async def test_catalog_page_limits_are_refused_before_provider_io(limit: int) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("Invalid limit reached provider"))
    ) as http:
        with pytest.raises(ValueError, match="page size"):
            await ComposioCatalogClient(http).list_toolkits(search="", cursor=None, limit=limit)


@pytest.mark.security
async def test_a_catalog_with_no_direct_actions_cannot_create_an_ambient_tool_grant() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"items": []}))
    ) as http:
        with pytest.raises(ExternalServiceError, match="no available direct actions"):
            await ComposioCatalogClient(http).direct_tool_names(toolkit="microsoft_teams")
