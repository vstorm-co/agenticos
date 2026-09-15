"""Signing in through a deployment's own identity provider (#1419).

A company self-hosting this runs an identity provider already, and will not mint
local passwords for its staff - so without OIDC its MFA and its offboarding are
solved twice. The provider is generic: an issuer, a client pair, and whatever
`<issuer>/.well-known/openid-configuration` says the endpoints are.

What is asserted here is the part that is ours. The authorization-code exchange
itself is authlib's and is stubbed; the conditions around it are not, and each
one below is a way somebody gets in who should not.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api.deps import get_redis
from app.core import oauth as oauth_module
from app.core.config import settings
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.oauth import redirect_uri_for, sign_in_client, verified_identity
from app.main import app
from app.services.user import UserService

pytestmark = pytest.mark.anyio

_LOGIN = f"{settings.API_V1_STR}/oauth/oidc/login"
_CALLBACK = f"{settings.API_V1_STR}/oauth/oidc/callback"

_CLAIMS = {"sub": "s-1", "email": "ada@corp.example", "name": "Ada", "email_verified": True}


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        self._store[key] = value
        return True

    async def getdel(self, key: str) -> str | None:
        return self._store.pop(key, None)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that has pointed itself at an issuer."""
    monkeypatch.setattr(settings, "OIDC_ISSUER", "https://id.corp.example/realms/staff")
    monkeypatch.setattr(settings, "OIDC_CLIENT_ID", "agenticos")
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "shh")
    monkeypatch.setattr(oauth_module, "_oidc_client", None)


class TestWhatTheClaimsHaveToSay:
    """`verified_identity` is the whole of what a token has to prove."""

    def test_a_verified_address_with_a_subject_signs_in(self) -> None:
        assert verified_identity(_CLAIMS) == ("s-1", "ada@corp.example", "Ada")

    def test_an_unverified_address_is_refused(self) -> None:
        """The sign-up policy's domain allow-list is built on an address meaning
        something. A provider that lets somebody set an unverified one is a
        provider on which anybody claims anybody's work address."""
        assert verified_identity({**_CLAIMS, "email_verified": False}) is None

    def test_an_absent_verification_claim_counts_as_unverified(self) -> None:
        """Believing an omission is the same hole as believing a false: a
        deployment whose provider does not send the claim configures it to."""
        assert verified_identity({"sub": "s-1", "email": "ada@corp.example"}) is None

    def test_no_subject_is_refused(self) -> None:
        """`sub` is the only stable identifier - an address changes hands, and
        matching on it alone hands the next holder the previous holder's work."""
        assert verified_identity({"email": "ada@corp.example", "email_verified": True}) is None

    def test_no_address_is_refused(self) -> None:
        assert verified_identity({"sub": "s-1", "email_verified": True}) is None

    def test_an_empty_userinfo_is_refused(self) -> None:
        assert verified_identity(None) is None

    def test_a_missing_name_is_not_a_refusal(self) -> None:
        """A display name is decoration; an account without one is fine."""
        assert verified_identity({**_CLAIMS, "name": None}) == ("s-1", "ada@corp.example", None)


class TestWhichProvidersExist:
    def test_an_unconfigured_deployment_has_no_oidc_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not a redirect at an empty issuer, and not a different answer from the
        one an invented provider gets: which identity provider a company runs is
        not a fact a stranger enumerates by guessing paths."""
        monkeypatch.setattr(settings, "OIDC_ISSUER", "")
        monkeypatch.setattr(oauth_module, "_oidc_client", None)
        with pytest.raises(NotFoundError):
            sign_in_client("oidc")

    def test_an_invented_provider_is_refused(self) -> None:
        with pytest.raises(NotFoundError):
            sign_in_client("okta-but-made-up")

    def test_a_configured_deployment_gets_a_client_asking_for_pkce(self, configured: None) -> None:
        """An authorization code intercepted between the provider and this
        callback is useless without the browser that started the flow."""
        client = sign_in_client("oidc")

        assert client.client_kwargs["code_challenge_method"] == "S256"
        assert client._server_metadata_url == (
            "https://id.corp.example/realms/staff/.well-known/openid-configuration"
        )

    def test_the_client_is_kept_while_the_configuration_is_unchanged(
        self, configured: None
    ) -> None:
        """Authlib caches the discovery document and the JWKS on the client, so
        rebuilding it per sign-in would refetch both every time."""
        assert sign_in_client("oidc") is sign_in_client("oidc")

    def test_google_is_still_reachable_under_its_own_name(self) -> None:
        assert sign_in_client("google") is oauth_module.oauth.google

    def test_each_provider_returns_to_its_own_registered_uri(self) -> None:
        """The value has to match the one registered at the provider exactly, so
        it is configuration rather than something built from the request."""
        assert redirect_uri_for("google") == settings.GOOGLE_REDIRECT_URI
        assert redirect_uri_for("oidc") == settings.OIDC_REDIRECT_URI


class TestTheRoundTrip:
    async def test_the_login_route_redirects_to_the_provider(
        self, client: AsyncClient, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sign_in_client("oidc"),
            "authorize_redirect",
            AsyncMock(return_value=SimpleNamespace(status_code=302)),
        )

        resp = await client.get(_LOGIN)

        assert resp.status_code == 200

    async def test_an_unconfigured_deployment_answers_the_login_route_with_404(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OIDC_ISSUER", "")
        monkeypatch.setattr(oauth_module, "_oidc_client", None)

        resp = await client.get(_LOGIN)

        assert resp.status_code == 404

    async def test_a_verified_sign_in_ends_at_the_frontend_with_a_code(
        self, client: AsyncClient, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app.dependency_overrides[get_redis] = _FakeRedis
        monkeypatch.setattr(
            sign_in_client("oidc"),
            "authorize_access_token",
            AsyncMock(return_value={"userinfo": _CLAIMS}),
        )
        created = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        monkeypatch.setattr(UserService, "get_or_create_oauth_user", created)

        resp = await client.get(_CALLBACK)

        assert resp.status_code == 307
        query = parse_qs(urlparse(resp.headers["location"]).query)
        assert "code" in query
        # The account is keyed on this provider's own subject, not on the address.
        assert created.await_args.kwargs["provider"] == "oidc"
        assert created.await_args.kwargs["provider_id"] == "s-1"

    async def test_an_unverified_address_never_reaches_account_creation(
        self, client: AsyncClient, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app.dependency_overrides[get_redis] = _FakeRedis
        monkeypatch.setattr(
            sign_in_client("oidc"),
            "authorize_access_token",
            AsyncMock(return_value={"userinfo": {**_CLAIMS, "email_verified": False}}),
        )
        created = AsyncMock()
        monkeypatch.setattr(UserService, "get_or_create_oauth_user", created)

        resp = await client.get(_CALLBACK)

        assert resp.status_code == 307
        assert "error=" in resp.headers["location"]
        created.assert_not_awaited()

    async def test_the_sign_up_policy_refuses_an_oidc_sign_in_as_it_refuses_a_registration(
        self, client: AsyncClient, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An `invite_only` or domain-limited deployment that let the SSO button
        through would not be closed at all - and nothing about an OIDC callback
        looks like a registration. The policy's own sentence is carried to the
        login page, because it was written for the person reading it.
        """
        app.dependency_overrides[get_redis] = _FakeRedis
        monkeypatch.setattr(
            sign_in_client("oidc"),
            "authorize_access_token",
            AsyncMock(return_value={"userinfo": _CLAIMS}),
        )
        monkeypatch.setattr(
            UserService,
            "get_or_create_oauth_user",
            AsyncMock(
                side_effect=AuthorizationError(
                    message="This deployment is invite-only. Ask an administrator to invite you."
                )
            ),
        )

        resp = await client.get(_CALLBACK)

        assert resp.status_code == 307
        location = urlparse(resp.headers["location"])
        assert location.path == "/login"
        assert parse_qs(location.query)["error"] == [
            "This deployment is invite-only. Ask an administrator to invite you."
        ]
