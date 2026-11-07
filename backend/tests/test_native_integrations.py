"""Native products never let a model choose a host, borrow another account or bypass approval."""

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.agents.capabilities import get
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.approval._policy import approval_required_tools
from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
)
from app.db.models.mcp_connection import McpConnection
from app.services.integrations import client
from app.services.integrations.catalog import PRODUCTS
from app.services.integrations.service import AccountSelection, IntegrationService
from app.services.integrations.setup import setup_for
from app.services.mcp_connection import McpConnectionService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def account(**changes: object) -> McpConnection:
    values: dict[str, object] = {
        "id": uuid4(),
        "scope": "user",
        "purpose": "account",
        "catalog_key": "google",
        "user_id": uuid4(),
        "name": "work",
        "label": "Work",
        "is_enabled": True,
        "granted_scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    }
    return McpConnection(**(values | changes))


@pytest.mark.parametrize("product", PRODUCTS.values(), ids=lambda p: p.id)
async def test_every_product_offers_exactly_its_declared_tools_and_writes_require_approval(product):
    definition = get(product.id)
    built = definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id=product.id),
            config=definition.validate_config({}),
        )
    )
    offered = built.get_toolset().tools
    assert set(offered) == definition.tool_ids
    spec = AgentSpec.model_validate({"name": "Native", "capabilities": [{"id": product.id}]})
    assert approval_required_tools(spec) == frozenset(
        f"{product.id}_{op.id}" for op in product.operations if op.side_effecting
    )


@pytest.mark.parametrize("provider", ["google", "microsoft", "slack"])
async def test_setup_permissions_are_the_operations_consent_will_request(provider):
    setup = setup_for(provider)
    for product in setup.products:
        assert set(product.read_scopes) == {
            scope
            for op in PRODUCTS[product.id].operations
            if not op.side_effecting
            for scope in (op.scopes if provider == "slack" else op.scopes[:1])
        }
    if provider == "slack":
        import json

        manifest = json.loads(parse_qs(urlparse(setup.manifest_url).query)["manifest_json"][0])
        assert manifest["oauth_config"]["redirect_urls"] == [setup.redirect_uri]


async def test_a_personal_account_is_never_used_without_a_current_member(monkeypatch):
    service = IntegrationService(AsyncMock())
    product = PRODUCTS["gmail"]
    with pytest.raises(AuthorizationError, match="no person"):
        await service.account(product, AccountSelection(), organization_id=uuid4(), person_id=None)
    monkeypatch.setattr(
        "app.services.integrations.service.member_repo.get_active", AsyncMock(return_value=None)
    )
    with pytest.raises(AuthorizationError, match="membership"):
        await service.account(
            product, AccountSelection(), organization_id=uuid4(), person_id=uuid4()
        )


async def test_two_named_accounts_are_targeted_without_crossing_organization(monkeypatch):
    org, other_org, person = uuid4(), uuid4(), uuid4()
    work = account(user_id=person, account_source_organization_id=org)
    private = account(
        user_id=person, name="private", label="Personal", account_source_organization_id=org
    )
    foreign = account(user_id=person, name="other", account_source_organization_id=other_org)
    monkeypatch.setattr(
        "app.services.integrations.service.member_repo.get_active", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(
        "app.services.integrations.service.mcp_connection_repo.list_accounts",
        AsyncMock(return_value=[work, private, foreign]),
    )
    service = IntegrationService(AsyncMock())
    assert (
        await service.account(
            PRODUCTS["gmail"],
            AccountSelection(account_name="private"),
            organization_id=org,
            person_id=person,
        )
        is private
    )
    for name in ["", "other"]:
        with pytest.raises(BadRequestError, match="unambiguous"):
            await service.account(
                PRODUCTS["gmail"],
                AccountSelection(account_name=name),
                organization_id=org,
                person_id=person,
            )


@pytest.mark.parametrize("wrong", ["owner", "provider", "disabled"])
async def test_an_organization_binding_refuses_foreign_or_disabled_accounts(monkeypatch, wrong):
    org = uuid4()
    row = account(
        scope="org",
        organization_id=uuid4() if wrong == "owner" else org,
        catalog_key="microsoft" if wrong == "provider" else "google",
        is_enabled=wrong != "disabled",
    )
    monkeypatch.setattr(
        "app.services.integrations.service.mcp_connection_repo.get_account",
        AsyncMock(return_value=row),
    )
    with pytest.raises((NotFoundError, AuthorizationError)):
        await IntegrationService(AsyncMock()).account(
            PRODUCTS["gmail"],
            AccountSelection(account="organization", connection_id=row.id),
            organization_id=org,
            person_id=None,
        )


async def test_missing_scope_prevents_even_unsealing_the_token(monkeypatch):
    service = IntegrationService(AsyncMock())
    monkeypatch.setattr(service, "account", AsyncMock(return_value=account()))
    token = AsyncMock()
    monkeypatch.setattr(McpConnectionService, "integration_access_token", token)
    with pytest.raises(AuthorizationError, match="permissions"):
        await service.run(
            "gmail",
            "send_message",
            AccountSelection(),
            organization_id=uuid4(),
            person_id=uuid4(),
            parameters={},
            query={},
            body={"raw": "abc"},
        )
    token.assert_not_awaited()


async def test_the_native_transport_encodes_identifiers_and_never_follows_redirects(monkeypatch):
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://attacker.invalid/token"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    operation = PRODUCTS["gmail"].operations[1]
    with pytest.raises(ExternalServiceError):
        await client.execute(
            operation,
            SecretStr("private-token"),
            parameters={"thread_id": "a/b?token=leak"},
            query={},
            body=None,
        )
    assert len(seen) == 1
    assert seen[0].url.host == "gmail.googleapis.com"
    assert b"a%2Fb%3Ftoken%3Dleak" in seen[0].url.raw_path


@pytest.mark.parametrize(
    "parameters,query",
    [({}, {}), ({"thread_id": "id", "url": "x"}, {}), ({"thread_id": "id"}, {"access_token": "x"})],
)
async def test_unknown_arguments_cannot_override_the_authenticated_request(parameters, query):
    with pytest.raises(BadRequestError):
        await client.execute(
            PRODUCTS["gmail"].operations[1],
            SecretStr("secret"),
            parameters=parameters,
            query=query,
            body=None,
        )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[]),
        httpx.Response(500),
        httpx.Response(200, content=b"x" * 2_000_001),
    ],
)
async def test_bad_provider_responses_are_explicit_failures(monkeypatch, response):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(lambda _: response), **kw),
    )
    with pytest.raises(ExternalServiceError):
        await client.execute(
            PRODUCTS["gmail"].operations[0], SecretStr("secret"), parameters={}, query={}, body=None
        )


async def test_slack_http_success_with_ok_false_is_still_a_failure(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
            ),
            **kw,
        ),
    )
    with pytest.raises(ExternalServiceError, match="Slack refused"):
        await client.execute(
            PRODUCTS["slack"].operations[0], SecretStr("secret"), parameters={}, query={}, body=None
        )


@pytest.mark.parametrize("other_label", ["Work", "private"])
async def test_unique_account_names_take_precedence_over_ambiguous_display_labels(
    monkeypatch, other_label
):
    org, person = uuid4(), uuid4()
    first = account(name="first", label=other_label, account_source_organization_id=org)
    selected = account(name="private", label="Work", account_source_organization_id=org)
    monkeypatch.setattr(
        "app.services.integrations.service.member_repo.get_active", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(
        "app.services.integrations.service.mcp_connection_repo.list_accounts",
        AsyncMock(return_value=[first, selected]),
    )
    assert (
        await IntegrationService(AsyncMock()).account(
            PRODUCTS["gmail"],
            AccountSelection(account_name="private"),
            organization_id=org,
            person_id=person,
        )
        is selected
    )


async def test_graph_folder_pagination_keeps_the_fixed_endpoint_and_encodes_the_skip_token(
    monkeypatch,
):
    real_client = httpx.AsyncClient
    seen = []

    def respond(request):
        seen.append(request)
        if "$skipToken" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "value": [{"id": "first"}],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/drives/drive/items/folder/children?$skipToken=next%2Bpage%2F%3D",
                },
            )
        assert request.url.params["$skipToken"] == "next+page/="
        return httpx.Response(200, json={"value": [{"id": "last"}]})

    monkeypatch.setattr(
        client.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    operation = next(
        op for op in PRODUCTS["microsoft_files"].operations if op.id == "list_children"
    )
    first = await client.execute(
        operation,
        SecretStr("private"),
        parameters={"drive_id": "drive", "item_id": "folder"},
        query={},
        body=None,
    )
    token = parse_qs(urlparse(first["@odata.nextLink"]).query)["$skipToken"][0]
    second = await client.execute(
        operation,
        SecretStr("private"),
        parameters={"drive_id": "drive", "item_id": "folder"},
        query={"$skipToken": token},
        body=None,
    )
    assert second["value"] == [{"id": "last"}]
    assert all(
        request.url.host == "graph.microsoft.com"
        and request.url.path == "/v1.0/drives/drive/items/folder/children"
        for request in seen
    )
