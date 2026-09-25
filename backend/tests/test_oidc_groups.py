"""OIDC sign-in applying the provider's groups to directory-managed memberships (#1773).

With `OIDC_GROUPS_CLAIM` unset nothing here happens, and the existing sign-in
tests (`test_oidc_sign_in.py`) are that case. Set, the claim is read from the ID
token or UserInfo, an Entra group overage is refused rather than read as "no
groups", a mapped group admits past `invite_only`, and the sync runs for the
deployment's own provider only - never for Google.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api.deps import get_redis
from app.api.routes.v1._oauth_claims import claims_for
from app.core import oauth as oauth_module
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.oauth import groups_claim, sign_in_client
from app.main import app
from app.services.directory import DirectorySyncService
from app.services.user import UserService

pytestmark = pytest.mark.anyio

_CALLBACK = f"{settings.API_V1_STR}/oauth/oidc/callback"
_CLAIMS = {"sub": "s-1", "email": "ada@corp.example", "email_verified": True}


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        self._store[key] = value
        return True

    async def getdel(self, key: str) -> str | None:
        return self._store.pop(key, None)


@pytest.fixture
def reads_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "OIDC_GROUPS_CLAIM", "groups")


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, reads_groups: None) -> None:
    monkeypatch.setattr(settings, "OIDC_ISSUER", "https://id.corp.example/realms/staff")
    monkeypatch.setattr(settings, "OIDC_CLIENT_ID", "agenticos")
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "shh")
    monkeypatch.setattr(oauth_module, "_oidc_client", None)


class TestTheGroupsClaim:
    def test_unset_means_groups_are_not_read_at_all(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "OIDC_GROUPS_CLAIM", "")

        assert groups_claim({"groups": ["a"]}) is None

    def test_a_list_of_names_is_read_and_anything_else_in_it_ignored(self, reads_groups) -> None:
        assert groups_claim({"groups": ["Finance", 7, "Ops"]}) == frozenset({"Finance", "Ops"})

    def test_a_single_string_is_one_group(self, reads_groups) -> None:
        assert groups_claim({"groups": "Finance"}) == frozenset({"Finance"})

    def test_an_absent_claim_is_no_groups(self, reads_groups) -> None:
        """Keycloak and Okta omit an empty list; leaving the last group must still count."""
        assert groups_claim({"sub": "s"}) == frozenset()
        assert groups_claim(None) == frozenset()
        assert groups_claim({"groups": {"not": "a list"}}) == frozenset()

    @pytest.mark.security
    def test_an_entra_overage_is_refused_rather_than_read_as_no_groups(self, reads_groups) -> None:
        """Past 200 groups Entra names a Graph endpoint instead; the token then says nothing."""
        with pytest.raises(AuthenticationError):
            groups_claim({"_claim_names": {"groups": "src1"}, "_claim_sources": {}})


class TestWhereTheClaimComesFrom:
    async def test_userinfo_is_asked_when_the_token_lacks_the_groups(self, reads_groups) -> None:
        client = SimpleNamespace(userinfo=AsyncMock(return_value={"groups": ["Finance"]}))

        claims = await claims_for(client, {"userinfo": dict(_CLAIMS)})

        assert claims is not None
        assert claims["groups"] == ["Finance"]
        client.userinfo.assert_awaited_once()

    async def test_a_token_already_carrying_them_needs_no_round_trip(self, reads_groups) -> None:
        client = SimpleNamespace(userinfo=AsyncMock())

        claims = await claims_for(client, {"userinfo": {**_CLAIMS, "groups": []}})

        assert claims is not None
        client.userinfo.assert_not_awaited()


class TestTheCallback:
    async def test_a_mapped_group_admits_and_the_sync_applies_the_groups(
        self, client: AsyncClient, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app.dependency_overrides[get_redis] = _FakeRedis
        monkeypatch.setattr(
            sign_in_client("oidc"),
            "authorize_access_token",
            AsyncMock(return_value={"userinfo": {**_CLAIMS, "groups": ["Finance"]}}),
        )
        user = SimpleNamespace(id=uuid4())
        created = AsyncMock(return_value=user)
        monkeypatch.setattr(UserService, "get_or_create_oauth_user", created)
        admits = AsyncMock(return_value=True)
        apply = AsyncMock()
        monkeypatch.setattr(DirectorySyncService, "admits", admits)
        monkeypatch.setattr(DirectorySyncService, "apply", apply)

        resp = await client.get(_CALLBACK)

        assert resp.status_code == 307
        assert "code" in parse_qs(urlparse(resp.headers["location"]).query)
        assert created.await_args.kwargs["admitted_by_directory"] is True
        assert apply.await_args.args == (user.id, frozenset({"Finance"}))
        assert apply.await_args.kwargs == {"provider": "oidc"}

    @pytest.mark.security
    async def test_an_overage_goes_back_to_the_sign_in_page_and_touches_nothing(
        self, client: AsyncClient, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app.dependency_overrides[get_redis] = _FakeRedis
        monkeypatch.setattr(
            sign_in_client("oidc"),
            "authorize_access_token",
            AsyncMock(return_value={"userinfo": {**_CLAIMS, "_claim_names": {"groups": "src1"}}}),
        )
        created = AsyncMock()
        monkeypatch.setattr(UserService, "get_or_create_oauth_user", created)
        monkeypatch.setattr(sign_in_client("oidc"), "userinfo", AsyncMock(return_value={}))

        resp = await client.get(_CALLBACK)

        assert "error=" in resp.headers["location"]
        created.assert_not_awaited()

    async def test_google_never_touches_memberships(
        self, client: AsyncClient, reads_groups: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app.dependency_overrides[get_redis] = _FakeRedis
        monkeypatch.setattr(
            sign_in_client("google"),
            "authorize_access_token",
            AsyncMock(return_value={"userinfo": {**_CLAIMS, "groups": ["Finance"]}}),
        )
        created = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        monkeypatch.setattr(UserService, "get_or_create_oauth_user", created)
        apply = AsyncMock()
        monkeypatch.setattr(DirectorySyncService, "apply", apply)

        await client.get(f"{settings.API_V1_STR}/oauth/google/callback")

        assert created.await_args.kwargs["admitted_by_directory"] is False
        apply.assert_not_awaited()
