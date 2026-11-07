"""Connected accounts through the app (#2191).

A person's own accounts are theirs to connect with no organization permission; the
organization's take `mcp:manage` to connect or disconnect and `connections:view`
to list. No response carries a token.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.mcp_connection import McpConnection
from app.main import app

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _account() -> McpConnection:
    return McpConnection(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        scope="user",
        catalog_key="google",
        purpose="account",
        name="google:ana@acme.com",
        label="ana@acme.com",
        url="https://www.googleapis.com",
        secret_key_version=1,
        auth_type="oauth",
        oauth_payload="sealed-refresh-token",
        granted_scopes=["https://www.googleapis.com/auth/drive"],
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list_accounts = AsyncMock(return_value=[_account()])
    stub.account_start = AsyncMock(return_value="https://accounts.google.com/o/oauth2/v2/auth?x=1")
    stub.delete_account = AsyncMock(return_value=None)
    stub.oauth_callback = AsyncMock(return_value=_account())
    return stub


def _client(service: MagicMock, mock_redis: MagicMock, role: str):
    context = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_mcp_connection_service] = lambda: service

    @asynccontextmanager
    async def opened() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

    return opened


@pytest.fixture
def owner(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    yield _client(service, mock_redis, OrgRoleName.OWNER)
    app.dependency_overrides.clear()


@pytest.fixture
def viewer(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    yield _client(service, mock_redis, OrgRoleName.VIEWER)
    app.dependency_overrides.clear()


def _url(tail: str) -> str:
    return f"{settings.API_V1_STR}{tail}"


@pytest.mark.parametrize("prefix", ["/me/connected-accounts", "/connected-accounts"])
async def test_an_account_is_listed_by_its_address_and_never_its_token(owner, prefix) -> None:
    async with owner() as client:
        response = await client.get(_url(prefix))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1 and body["items"][0]["email"] == "ana@acme.com"
    assert "sealed-refresh-token" not in response.text


@pytest.mark.parametrize(
    ("prefix", "for_organization"),
    [("/me/connected-accounts", False), ("/connected-accounts", True)],
)
async def test_connecting_and_disconnecting_reach_the_right_owner(
    owner, service, prefix, for_organization
) -> None:
    async with owner() as client:
        started = await client.post(_url(f"{prefix}/oauth/start"), json={"browser_nonce": "n" * 43})
        deleted = await client.delete(_url(f"{prefix}/{uuid.uuid4()}"))
    assert started.status_code == 200
    assert started.json()["authorization_url"].startswith("https://accounts.google.com/")
    assert deleted.status_code == 204
    assert service.account_start.await_args.kwargs == {
        "for_organization": for_organization,
        "browser_nonce": "n" * 43,
        "provider": "google",
        "products": None,
        "label": "",
        "write": False,
    }
    assert service.delete_account.await_args.kwargs == {"for_organization": for_organization}


async def test_a_viewer_connects_their_own_account_but_not_the_organizations(
    viewer, service
) -> None:
    async with viewer() as client:
        mine = await client.post(
            _url("/me/connected-accounts/oauth/start"), json={"browser_nonce": "n" * 43}
        )
        orgs = await client.post(
            _url("/connected-accounts/oauth/start"), json={"browser_nonce": "n" * 43}
        )
        gone = await client.delete(_url(f"/connected-accounts/{uuid.uuid4()}"))
    assert mine.status_code == 200
    assert orgs.status_code == 403 and gone.status_code == 403
    assert service.account_start.await_count == 1
    service.delete_account.assert_not_called()


async def test_the_builder_reads_what_the_terminal_can_mount(owner) -> None:
    async with owner() as client:
        response = await client.get(_url("/agents/capabilities/mirage/backends"))
    assert response.status_code == 200
    body = response.json()
    assert body["installed"] is True
    github = next(item for item in body["items"] if item["name"] == "github")
    assert (
        github["secret_fields"] == ["token"]
        and "base_url" not in github["options_schema"]["properties"]
    )
    s3 = next(item for item in body["items"] if item["name"] == "s3")
    assert s3["available"] is False and s3["reason"]


async def test_an_accounts_consent_returns_by_its_address_with_nothing_to_add_to_an_agent(
    owner,
) -> None:
    async with owner() as client:
        response = await client.post(
            _url("/me/mcp-connections/oauth/callback"), json={"state": "s", "code": "c"}
        )
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "connection_name": "ana@acme.com",
        "connection_id": None,
        "scope": None,
        "error": None,
    }


async def test_callback_passes_the_authenticated_actor_and_browser_nonce(owner, service) -> None:
    from app.db.models.user import User

    user = User(id=uuid.uuid4(), email="ana@acme.com", hashed_password="x", is_active=True)
    app.dependency_overrides[deps.get_optional_current_user] = lambda: user
    async with owner() as client:
        response = await client.post(
            _url("/me/mcp-connections/oauth/callback"),
            json={"state": "s", "code": "c", "browser_nonce": "n" * 43},
        )
    assert response.status_code == 200 and response.json()["ok"]
    service.oauth_callback.assert_awaited_once_with(
        state="s", code="c", browser_nonce="n" * 43, acting_user_id=user.id
    )


async def test_optional_oauth_identity_keeps_normal_authentication_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.requests import Request

    from app.core.exceptions import AuthenticationError
    from app.services.api_key import ApiKeyService
    from app.services.impersonation import ImpersonationService
    from app.services.session import SessionService
    from app.services.user import UserService

    db = AsyncMock()
    request = Request({"type": "http"})
    services = (UserService(db), ImpersonationService(db), SessionService(db), ApiKeyService(db))
    authenticate = AsyncMock(side_effect=AuthenticationError("expired session"))
    monkeypatch.setattr(deps, "get_current_user", authenticate)
    assert await deps.get_optional_current_user(request, None, *services) is None
    authenticate.assert_not_awaited()
    with pytest.raises(AuthenticationError, match="expired session"):
        await deps.get_optional_current_user(request, "expired", *services)
    authenticate.assert_awaited_once_with(request, "expired", *services)


@pytest.mark.parametrize(
    "prefix,organization", [("/me/connected-accounts", False), ("/connected-accounts", True)]
)
@pytest.mark.parametrize(
    "kind,tail,payload",
    [
        ("slack_token", "/slack/token", {"token": "xoxp-private-token", "label": "Client"}),
        (
            "imap_account",
            "/imap",
            {
                "credential": {
                    "host": "imap.example.com",
                    "username": "member",
                    "password": "app-password",
                },
                "label": "Mail",
            },
        ),
        (
            "application_account",
            "/application",
            {
                "provider": "microsoft",
                "secret_id": str(uuid.uuid4()),
                "subject": "00000000-0000-0000-0000-000000000001",
                "products": ["teams"],
            },
        ),
    ],
)
async def test_native_account_routes_preserve_owner_scope_and_never_return_credentials(
    owner, service, prefix, organization, kind, tail, payload
):
    method = AsyncMock(return_value=_account())
    setattr(service, f"connect_{kind}", method)
    async with owner() as client:
        response = await client.post(_url(prefix + tail), json=payload)
    assert response.status_code == 201, response.text
    assert method.await_args.kwargs.get("for_organization", True) is organization
    assert all(
        secret not in response.text
        for secret in ["xoxp-private-token", "app-password", "sealed-refresh-token"]
    )


@pytest.mark.parametrize(
    "tail,payload",
    [
        ("/slack/token", {"token": "xoxp-private-token"}),
        (
            "/imap",
            {
                "credential": {
                    "host": "imap.example.com",
                    "username": "member",
                    "password": "app-password",
                }
            },
        ),
        (
            "/application",
            {"provider": "google", "secret_id": str(uuid.uuid4()), "products": ["gmail"]},
        ),
    ],
)
async def test_members_cannot_connect_an_organization_credential_without_manage_permission(
    viewer, service, tail, payload
):
    async with viewer() as client:
        response = await client.post(_url("/connected-accounts" + tail), json=payload)
    assert response.status_code == 403


async def test_setup_route_returns_the_same_scopes_and_callback_as_the_service(owner, service):
    from app.services.integrations import setup_for

    service.integration_setup.return_value = setup_for("slack", write=True)
    async with owner() as client:
        response = await client.get(_url("/me/connected-accounts/setup/slack?write=true"))
    assert response.status_code == 200
    assert response.json()["manifest_url"] == setup_for("slack", write=True).manifest_url
    service.integration_setup.assert_called_once_with("slack", write=True)


@pytest.mark.parametrize(
    "prefix,organization", [("/me/connected-accounts", False), ("/connected-accounts", True)]
)
async def test_odoo_api_seals_under_the_selected_owner_and_returns_no_api_key(
    owner, service, prefix, organization
):
    row = _account()
    row.catalog_key, row.auth_type = "odoo", "odoo"
    service.connect_odoo_account = AsyncMock(return_value=row)
    async with owner() as client:
        result = await client.post(
            _url(prefix + "/odoo"),
            json={
                "credential": {
                    "origin": "https://erp.example.com",
                    "database": "company",
                    "api_key": "private-api-key",
                },
                "label": "ERP",
                "write": False,
            },
        )
    assert result.status_code == 201, result.text
    assert result.json()["provider"] == "odoo"
    assert "private-api-key" not in result.text and "sealed-refresh-token" not in result.text
    assert service.connect_odoo_account.await_args.kwargs["for_organization"] is organization


async def test_odoo_org_api_requires_connection_management(viewer, service):
    async with viewer() as client:
        result = await client.post(
            _url("/connected-accounts/odoo"),
            json={
                "credential": {
                    "origin": "https://erp.example.com",
                    "database": "company",
                    "api_key": "private-api-key",
                }
            },
        )
    assert result.status_code == 403
