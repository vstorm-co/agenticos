"""Branded sign-in preserves verified identities and the existing admission path."""

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.core import oauth as oauth_module
from app.core.config import settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.oauth import identity_key, redirect_uri_for, sign_in_client
from app.services.sign_in_identity import github_claims
from app.services.user import UserService

pytestmark = pytest.mark.anyio
_TENANT = UUID("047458cc-1745-4f32-93f5-fd1ddaf8aa29")


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    for provider in ("GITHUB", "MICROSOFT"):
        monkeypatch.setattr(settings, f"{provider}_CLIENT_ID", "signin-client")
        monkeypatch.setattr(settings, f"{provider}_CLIENT_SECRET", SecretStr("signin-secret"))
    monkeypatch.setattr(settings, "MICROSOFT_TENANT_ID", _TENANT)
    monkeypatch.setattr(oauth_module, "_branded_clients", {})


def _github_http(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    real_client = httpx.AsyncClient

    def client(**kwargs: object) -> httpx.AsyncClient:
        assert kwargs["follow_redirects"] is False
        assert kwargs["timeout"] == 10
        assert kwargs["headers"] == {
            "Authorization": "Bearer test-token",
            "Accept": "application/vnd.github+json",
        }
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", client)


@pytest.mark.parametrize("provider", ["microsoft", "github"])
async def test_login_uses_pkce_and_a_browser_bound_state(
    provider: str, configured: None, client: httpx.AsyncClient
) -> None:
    if provider == "microsoft":
        sign_in_client(provider).server_metadata.update(
            authorization_endpoint=f"https://login.microsoftonline.com/{_TENANT}/oauth2/v2.0/authorize"
        )
    response = await client.get(f"{settings.API_V1_STR}/oauth/{provider}/login")
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43
    assert query["state"][0]
    assert query["redirect_uri"] == [redirect_uri_for(provider)]
    assert query["scope"] == ["openid email profile" if provider == "microsoft" else "user:email"]


@pytest.mark.security
@pytest.mark.parametrize("provider", ["microsoft", "github"])
async def test_unconfigured_provider_refuses_login(
    provider: str, configured: None, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, f"{provider.upper()}_CLIENT_SECRET", SecretStr(""))
    assert (await client.get(f"{settings.API_V1_STR}/oauth/{provider}/login")).status_code == 404


@pytest.mark.security
def test_microsoft_requires_a_specific_tenant(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MICROSOFT_TENANT_ID", None)
    with pytest.raises(NotFoundError):
        sign_in_client("microsoft")


def test_clients_are_rebuilt_when_credentials_rotate(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for provider in ("microsoft", "github"):
        first = sign_in_client(provider)
        assert sign_in_client(provider) is first
        monkeypatch.setattr(settings, f"{provider.upper()}_CLIENT_SECRET", SecretStr("rotated"))
        assert sign_in_client(provider) is not first


@pytest.mark.security
def test_microsoft_subjects_cannot_collide_between_tenants(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = identity_key("microsoft", "subject")
    monkeypatch.setattr(settings, "MICROSOFT_TENANT_ID", uuid4())
    assert identity_key("microsoft", "subject") != first
    assert identity_key("github", "123") == "123"


@pytest.mark.parametrize("token", [None, "", 123])
async def test_missing_github_token_refuses_identity(token: object) -> None:
    assert await github_claims(token) is None


async def test_github_uses_numeric_id_and_verified_primary_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user":
            return httpx.Response(
                200, json={"id": 123, "login": "mutable-name", "email": "other@example.com"}
            )
        assert request.url.path == "/user/emails"
        return httpx.Response(
            200,
            json=[
                {"email": "secondary@example.com", "primary": False, "verified": True},
                {"email": "primary@example.com", "primary": True, "verified": True},
            ],
        )

    _github_http(monkeypatch, handler)
    assert await github_claims("test-token") == {
        "sub": "123",
        "email": "primary@example.com",
        "email_verified": True,
        "name": None,
    }


@pytest.mark.security
@pytest.mark.parametrize("primary,verified", [(False, True), (True, False)])
async def test_github_refuses_unverified_or_secondary_email(
    primary: bool, verified: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        data = (
            {"id": 123}
            if request.url.path == "/user"
            else [{"email": "primary@example.com", "primary": primary, "verified": verified}]
        )
        return httpx.Response(200, json=data)

    _github_http(monkeypatch, handler)
    assert await github_claims("test-token") is None


@pytest.mark.parametrize("failure", ["redirect", "denied", "bad-profile", "bad-emails", "timeout"])
async def test_github_provider_failures_are_explicit(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("provider timed out")
        if failure in {"redirect", "denied"}:
            return httpx.Response(
                302 if failure == "redirect" else 401, headers={"Location": "https://other.example"}
            )
        if request.url.path == "/user":
            return httpx.Response(
                200, json={"id": True} if failure == "bad-profile" else {"id": 123}
            )
        return httpx.Response(200, content=b"not-json")

    _github_http(monkeypatch, handler)
    with pytest.raises(AuthenticationError, match="GitHub could not verify"):
        await github_claims("test-token")


@pytest.mark.parametrize("provider", ["microsoft", "github"])
async def test_callback_issues_only_a_local_exchange_code(
    provider: str, configured: None, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sign_in_client(provider),
        "authorize_access_token",
        AsyncMock(
            return_value={
                "access_token": "test-token",
                "userinfo": {"sub": "ms-sub", "email": "primary@example.com", "xms_edov": True},
            }
        ),
    )
    if provider == "github":

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"id": 123}
                if request.url.path == "/user"
                else [{"email": "primary@example.com", "primary": True, "verified": True}],
            )

        _github_http(monkeypatch, handler)
    created = AsyncMock(return_value=SimpleNamespace(id=uuid4(), is_active=True))
    monkeypatch.setattr(UserService, "get_or_create_oauth_user", created)
    response = await client.get(f"{settings.API_V1_STR}/oauth/{provider}/callback")
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert response.status_code == 307
    assert set(query) == {"code"}
    assert created.await_args.kwargs["provider"] == provider
    subject = "ms-sub" if provider == "microsoft" else "123"
    assert created.await_args.kwargs["provider_id"] == identity_key(provider, subject)


@pytest.mark.security
@pytest.mark.parametrize("provider", ["microsoft", "github"])
async def test_callback_without_browser_state_cannot_create_an_account(
    provider: str, configured: None, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = AsyncMock()
    monkeypatch.setattr(UserService, "get_or_create_oauth_user", created)
    response = await client.get(
        f"{settings.API_V1_STR}/oauth/{provider}/callback?code=intercepted&state=other"
    )
    assert "error=" in response.headers["location"]
    created.assert_not_awaited()


@pytest.mark.security
async def test_unverified_microsoft_email_never_reaches_account_creation(
    configured: None, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = sign_in_client("microsoft")
    monkeypatch.setattr(
        provider,
        "authorize_access_token",
        AsyncMock(
            return_value={
                "userinfo": {"sub": "subject", "email": "primary@example.com", "xms_edov": False},
            }
        ),
    )
    created = AsyncMock()
    monkeypatch.setattr(UserService, "get_or_create_oauth_user", created)
    response = await client.get(f"{settings.API_V1_STR}/oauth/microsoft/callback")
    assert "error=" in response.headers["location"]
    created.assert_not_awaited()


async def test_microsoft_does_not_read_the_generic_oidc_directory_groups(
    configured: None, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OIDC_GROUPS_CLAIM", "groups")
    provider = sign_in_client("microsoft")
    monkeypatch.setattr(
        provider,
        "authorize_access_token",
        AsyncMock(
            return_value={
                "userinfo": {"sub": "subject", "email": "primary@example.com", "xms_edov": True},
            }
        ),
    )
    userinfo = AsyncMock(side_effect=RuntimeError("must not fetch directory groups"))
    monkeypatch.setattr(provider, "userinfo", userinfo)
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(
            return_value=SimpleNamespace(id=uuid4(), is_active=True),
        ),
    )
    response = await client.get(f"{settings.API_V1_STR}/oauth/microsoft/callback")
    assert "code=" in response.headers["location"]
    userinfo.assert_not_awaited()
