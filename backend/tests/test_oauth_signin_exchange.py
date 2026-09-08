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
