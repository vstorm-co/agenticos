"""The OAuth sign-in redirect delivers a code, never the token pair (#14).

A token in the redirect URL reaches the browser address bar, the frontend
server's access log, and the `Referer` of the next same-origin request - and the
refresh token is good for a week. The callback therefore hands out a single-use
code that the frontend swaps for the pair server to server.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import anyio
import pytest
from httpx import AsyncClient
from starlette.responses import Response

from app.api import deps
from app.api.deps import get_redis, get_session_service
from app.api.routes.v1 import oauth as oauth_routes
from app.core.config import settings
from app.core.oauth import oauth
from app.core.security import verify_special_token, verify_token
from app.main import app
from app.services.oauth_exchange import OAuthExchangeService
from app.services.session import SessionService
from app.services.user import UserService

pytestmark = pytest.mark.anyio

_CALLBACK = f"{settings.API_V1_STR}/oauth/google/callback"
_OIDC_CALLBACK = f"{settings.API_V1_STR}/oauth/oidc/callback"
_EXCHANGE = f"{settings.API_V1_STR}/oauth/exchange"


class _FakeRedis:
    """An in-memory stand-in with the two methods the exchange touches."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def getdel(self, key: str) -> str | None:
        return self._store.pop(key, None)


async def test_a_code_redeems_its_pair_exactly_once() -> None:
    service = OAuthExchangeService(_FakeRedis())
    code = await service.issue(access_token="acc", refresh_token="ref")
    assert await service.redeem(code) == ("acc", "ref")
    assert await service.redeem(code) is None


async def test_an_unknown_code_redeems_to_none() -> None:
    service = OAuthExchangeService(_FakeRedis())
    assert await service.redeem("never-issued") is None


async def test_the_callback_redirect_carries_a_code_not_the_tokens(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_redis] = _FakeRedis
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        AsyncMock(
            return_value={
                "userinfo": {"sub": "s", "email": "u@e.com", "name": "U", "email_verified": True}
            }
        ),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), is_active=True)),
    )

    resp = await client.get(_CALLBACK)

    assert resp.status_code == 307
    location = resp.headers["location"]
    assert "code=" in location
    assert "access_token" not in location
    assert "refresh_token" not in location


async def test_oidc_signin_for_totp_user_redirects_to_mfa_without_issuing_tokens(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider identity is only the first factor for an MFA-enabled user."""
    user_id = uuid4()
    monkeypatch.setattr(settings, "OIDC_GROUPS_CLAIM", "groups")
    directory_sync = MagicMock()
    directory_sync.admits = AsyncMock(return_value=True)
    directory_sync.apply = AsyncMock()
    app.dependency_overrides[deps.get_directory_sync_service] = lambda: directory_sync
    fake = _FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake
    session_service = SessionService(MagicMock())
    session_service.create_session = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    app.dependency_overrides[get_session_service] = lambda: session_service
    make_access = MagicMock(return_value="must-not-be-created")
    make_refresh = MagicMock(return_value="must-not-be-created")
    issue_code = AsyncMock()
    monkeypatch.setattr(oauth_routes, "create_access_token", make_access)
    monkeypatch.setattr(oauth_routes, "create_refresh_token", make_refresh)
    monkeypatch.setattr(OAuthExchangeService, "issue", issue_code)
    oidc_client = MagicMock()
    oidc_client.authorize_access_token = AsyncMock(
        return_value={
            "userinfo": {
                "sub": "s",
                "email": "u@e.com",
                "name": "U",
                "email_verified": True,
                "groups": ["admins"],
            }
        }
    )
    monkeypatch.setattr(oauth_routes, "sign_in_client", lambda provider: oidc_client)
    oidc_user = SimpleNamespace(
        id=user_id,
        is_active=True,
        totp_enabled=True,
        credential_version=3,
        created_at=None,
        updated_at=None,
    )
    monkeypatch.setattr(UserService, "get_or_create_oauth_user", AsyncMock(return_value=oidc_user))

    response = await client.get(_OIDC_CALLBACK)

    assert response.status_code == 307
    location = urlparse(response.headers["location"])
    assert location.path == "/auth/callback"
    assert location.query == ""
    mfa_token = parse_qs(location.fragment)["mfa_token"][0]
    payload = verify_special_token(mfa_token, expected_type="mfa")
    assert payload is not None
    assert payload["sub"] == str(user_id)
    assert payload["cv"] == 3
    assert payload["jti"]
    directory_sync.apply.assert_not_awaited()
    make_access.assert_not_called()
    make_refresh.assert_not_called()
    issue_code.assert_not_awaited()
    session_service.create_session.assert_not_awaited()

    auth_user_service = MagicMock()
    auth_user_service.get_by_id = AsyncMock(return_value=oidc_user)
    auth_mfa_service = MagicMock()
    auth_mfa_service.verify_challenge = AsyncMock(return_value=True)
    app.dependency_overrides[deps.get_user_service] = lambda: auth_user_service
    app.dependency_overrides[deps.get_mfa_service] = lambda: auth_mfa_service

    verified = await client.post(
        f"{settings.API_V1_STR}/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": "123456"},
    )

    assert verified.status_code == 200
    directory_sync.apply.assert_awaited_once_with(user_id, frozenset({"admins"}), provider="oidc")
    assert not any(key.startswith("auth:mfa:oauth:") for key in fake._store)


async def test_exchange_returns_the_pair_for_a_valid_code(client: AsyncClient) -> None:
    fake = _FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake
    code = await OAuthExchangeService(fake).issue(access_token="acc", refresh_token="ref")

    resp = await client.post(_EXCHANGE, json={"code": code})

    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "acc"
    assert body["refresh_token"] == "ref"


async def test_exchange_refuses_an_unknown_code(client: AsyncClient) -> None:
    app.dependency_overrides[get_redis] = _FakeRedis

    resp = await client.post(_EXCHANGE, json={"code": "never-issued"})

    assert resp.status_code == 401


async def test_the_oauth_login_binds_its_access_token_to_a_session(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OAuth sign-in is an ordinary session: its access token carries a `sid`
    so signing out everywhere can revoke it, as for any other login (#1501)."""
    fake = _FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake
    session_service = MagicMock()
    session_service.create_session = AsyncMock()
    app.dependency_overrides[get_session_service] = lambda: session_service
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        AsyncMock(
            return_value={
                "userinfo": {"sub": "s", "email": "u@e.com", "name": "U", "email_verified": True}
            }
        ),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), is_active=True)),
    )

    redirect = await client.get(_CALLBACK)
    code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]
    exchanged = await client.post(_EXCHANGE, json={"code": code})

    payload = verify_token(exchanged.json()["access_token"])
    assert payload is not None
    # The row is created with exactly the id the token names.
    session_service.create_session.assert_awaited_once()
    assert str(session_service.create_session.await_args.kwargs["session_id"]) == payload["sid"]


async def test_a_failed_code_issue_leaves_no_session_row(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row is written only after the single-use code is issued, so a failure
    handing out the code leaves no phantom session behind (#1501 review)."""
    app.dependency_overrides[get_redis] = _FakeRedis
    session_service = MagicMock()
    session_service.create_session = AsyncMock()
    app.dependency_overrides[get_session_service] = lambda: session_service
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        AsyncMock(
            return_value={
                "userinfo": {"sub": "s", "email": "u@e.com", "name": "U", "email_verified": True}
            }
        ),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), is_active=True)),
    )
    monkeypatch.setattr(
        OAuthExchangeService, "issue", AsyncMock(side_effect=RuntimeError("exchange store down"))
    )

    redirect = await client.get(_CALLBACK)

    assert redirect.status_code == 307
    assert "error=" in redirect.headers["location"]
    session_service.create_session.assert_not_awaited()


async def test_a_desktop_sign_in_returns_through_the_deep_link(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Google's authorization endpoint refuses an embedded user-agent, so the
    shell hands the flow to the system browser - and the browser that finishes it
    is not the one the app is in. The result crosses back by a scheme the
    operating system routes (#1532)."""
    app.dependency_overrides[get_redis] = _FakeRedis
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        AsyncMock(
            return_value={
                "userinfo": {"sub": "s", "email": "u@e.com", "name": "U", "email_verified": True}
            }
        ),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), is_active=True)),
    )
    started = AsyncMock(return_value=Response(status_code=302))
    monkeypatch.setattr(oauth.google, "authorize_redirect", started)

    # One client, so the session cookie the login sets is the one the callback reads.
    await client.get(
        f"{settings.API_V1_STR}/oauth/google/login?client=desktop&desktop_nonce=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )
    # The marker is filed under the state this attempt was started with, so the
    # callback has to carry it back - which is what the provider does.
    state = started.await_args.kwargs["state"]
    redirect = await client.get(f"{_CALLBACK}?state={state}")

    assert redirect.status_code == 307
    location = redirect.headers["location"]
    assert location.startswith("agenticos://auth/callback?code=")
    # And the shell's own nonce rides back, so it can refuse a deep link it did
    # not ask for - any local process can invoke a custom scheme.
    assert "desktop_nonce=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM" in location


async def test_a_second_sign_in_does_not_steal_the_first_ones_destination(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One browser can hold two sign-ins at once, and they must not trade places.

    A desktop start followed by an ordinary one used to erase the desktop marker,
    or have the first callback consume it - so a result went to the wrong client
    although both attempts held a valid, separate state (#1532).
    """
    app.dependency_overrides[get_redis] = _FakeRedis
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        AsyncMock(
            return_value={
                "userinfo": {"sub": "s", "email": "u@e.com", "name": "U", "email_verified": True}
            }
        ),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), is_active=True)),
    )
    started = AsyncMock(return_value=Response(status_code=302))
    monkeypatch.setattr(oauth.google, "authorize_redirect", started)

    await client.get(
        f"{settings.API_V1_STR}/oauth/google/login?client=desktop&desktop_nonce=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )
    desktop_state = started.await_args.kwargs["state"]
    await client.get(f"{settings.API_V1_STR}/oauth/google/login")
    browser_state = started.await_args.kwargs["state"]

    # The browser's own callback goes to the console, and does not consume the
    # desktop's marker on the way past.
    browser = await client.get(f"{_CALLBACK}?state={browser_state}")
    assert browser.headers["location"].startswith(settings.FRONTEND_URL.rstrip("/"))

    desktop = await client.get(f"{_CALLBACK}?state={desktop_state}")
    assert desktop.headers["location"].startswith("agenticos://auth/callback?code=")


async def test_a_callback_with_no_state_goes_to_the_console(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The console is the safe default: a deep link is the narrower destination
    and must be earned by an attempt that asked for one."""
    app.dependency_overrides[get_redis] = _FakeRedis
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        AsyncMock(return_value={"userinfo": {"sub": "s", "email": "u@e.com", "name": "U"}}),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), is_active=True)),
    )
    monkeypatch.setattr(
        oauth.google, "authorize_redirect", AsyncMock(return_value=Response(status_code=302))
    )

    await client.get(f"{settings.API_V1_STR}/oauth/google/login?client=desktop")
    redirect = await client.get(_CALLBACK)

    assert redirect.headers["location"].startswith(settings.FRONTEND_URL.rstrip("/"))


async def test_an_ordinary_sign_in_still_returns_to_the_console(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_redis] = _FakeRedis
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        AsyncMock(return_value={"userinfo": {"sub": "s", "email": "u@e.com", "name": "U"}}),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), is_active=True)),
    )

    redirect = await client.get(_CALLBACK)

    assert redirect.headers["location"].startswith(settings.FRONTEND_URL.rstrip("/"))


async def test_the_return_scheme_is_the_deployments_not_the_callers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The callback builds a redirect out of it, so a scheme a caller could hand
    it on the way back would be an open redirect into whatever URL handler that
    machine has registered."""
    app.dependency_overrides[get_redis] = _FakeRedis
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        AsyncMock(return_value={"userinfo": {"sub": "s", "email": "u@e.com", "name": "U"}}),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), is_active=True)),
    )

    redirect = await client.get(f"{_CALLBACK}?client=desktop&scheme=evil")

    assert redirect.headers["location"].startswith(settings.FRONTEND_URL.rstrip("/"))


@pytest.mark.security
async def test_native_proof_rejects_an_intercepted_code_without_consuming_it():
    service = OAuthExchangeService(_FakeRedis())
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    code = await service.issue(
        access_token="access", refresh_token="refresh", code_challenge=challenge
    )
    assert await service.redeem(code) is None
    assert await service.redeem(code, code_verifier=challenge) is None
    assert await service.redeem(code, code_verifier="x" * 43) is None
    assert await service.redeem(code, code_verifier="invalid") is None
    assert await service.redeem(code, code_verifier=verifier) == ("access", "refresh")
    assert await service.redeem(code, code_verifier=verifier) is None


@pytest.mark.security
@pytest.mark.parametrize("suffix", ["", "&desktop_nonce=invalid"])
async def test_native_start_requires_the_public_s256_challenge(client, suffix):
    response = await client.get(f"{settings.API_V1_STR}/oauth/google/login?client=desktop{suffix}")
    assert response.status_code == 401


@pytest.mark.security
async def test_concurrent_native_redemption_has_exactly_one_winner():
    class RacingRedis(_FakeRedis):
        async def get(self, key: str) -> str | None:
            value = await super().get(key)
            await anyio.lowlevel.checkpoint()
            return value

    service = OAuthExchangeService(RacingRedis())
    code = await service.issue(access_token="access", refresh_token="refresh")
    answers = await asyncio.gather(service.redeem(code), service.redeem(code))
    assert answers.count(("access", "refresh")) == 1
    assert answers.count(None) == 1


@pytest.mark.security
async def test_native_exchange_http_requires_the_private_verifier(client):
    fake = _FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    code = await OAuthExchangeService(fake).issue(
        access_token="access",
        refresh_token="refresh",
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    )
    assert (await client.post(_EXCHANGE, json={"code": code})).status_code == 401
    assert (
        await client.post(_EXCHANGE, json={"code": code, "code_verifier": "x" * 43})
    ).status_code == 401
    response = await client.post(_EXCHANGE, json={"code": code, "code_verifier": verifier})
    assert response.status_code == 200
    assert response.json()["access_token"] == "access"


@pytest.mark.security
async def test_a_changed_cache_value_is_not_redeemed_using_an_earlier_proof():
    class ChangedRedis(_FakeRedis):
        async def getdel(self, key: str) -> str | None:
            await super().getdel(key)
            return "changed"

    service = OAuthExchangeService(ChangedRedis())
    code = await service.issue(access_token="access", refresh_token="refresh")
    assert await service.redeem(code) is None
