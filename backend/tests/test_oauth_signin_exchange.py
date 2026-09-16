"""The OAuth sign-in redirect delivers a code, never the token pair (#14).

A token in the redirect URL reaches the browser address bar, the frontend
server's access log, and the `Referer` of the next same-origin request - and the
refresh token is good for a week. The callback therefore hands out a single-use
code that the frontend swaps for the pair server to server.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from httpx import AsyncClient
from starlette.responses import Response

from app.api.deps import get_redis, get_session_service
from app.core.config import settings
from app.core.oauth import oauth
from app.core.security import verify_token
from app.main import app
from app.services.oauth_exchange import OAuthExchangeService
from app.services.user import UserService

pytestmark = pytest.mark.anyio

_CALLBACK = f"{settings.API_V1_STR}/oauth/google/callback"
_EXCHANGE = f"{settings.API_V1_STR}/oauth/exchange"


class _FakeRedis:
    """An in-memory stand-in with the two methods the exchange touches."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        self._store[key] = value
        return True

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
        AsyncMock(return_value={"userinfo": {"sub": "s", "email": "u@e.com", "name": "U"}}),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )

    resp = await client.get(_CALLBACK)

    assert resp.status_code == 307
    location = resp.headers["location"]
    assert "code=" in location
    assert "access_token" not in location
    assert "refresh_token" not in location


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
        AsyncMock(return_value={"userinfo": {"sub": "s", "email": "u@e.com", "name": "U"}}),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
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
        AsyncMock(return_value={"userinfo": {"sub": "s", "email": "u@e.com", "name": "U"}}),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
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
        AsyncMock(return_value={"userinfo": {"sub": "s", "email": "u@e.com", "name": "U"}}),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    started = AsyncMock(return_value=Response(status_code=302))
    monkeypatch.setattr(oauth.google, "authorize_redirect", started)

    # One client, so the session cookie the login sets is the one the callback reads.
    await client.get(f"{settings.API_V1_STR}/oauth/google/login?client=desktop&desktop_nonce=n0nce")
    # The marker is filed under the state this attempt was started with, so the
    # callback has to carry it back - which is what the provider does.
    state = started.await_args.kwargs["state"]
    redirect = await client.get(f"{_CALLBACK}?state={state}")

    assert redirect.status_code == 307
    location = redirect.headers["location"]
    assert location.startswith("agenticos://auth/callback?code=")
    # And the shell's own nonce rides back, so it can refuse a deep link it did
    # not ask for - any local process can invoke a custom scheme.
    assert "desktop_nonce=n0nce" in location


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
        AsyncMock(return_value={"userinfo": {"sub": "s", "email": "u@e.com", "name": "U"}}),
    )
    monkeypatch.setattr(
        UserService,
        "get_or_create_oauth_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    started = AsyncMock(return_value=Response(status_code=302))
    monkeypatch.setattr(oauth.google, "authorize_redirect", started)

    await client.get(f"{settings.API_V1_STR}/oauth/google/login?client=desktop&desktop_nonce=n0nce")
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
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
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
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
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
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )

    redirect = await client.get(f"{_CALLBACK}?client=desktop&scheme=evil")

    assert redirect.headers["location"].startswith(settings.FRONTEND_URL.rstrip("/"))
