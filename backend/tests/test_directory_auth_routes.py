"""The directory sign-in routes: an LDAP password, and a Kerberos ticket (#1773).

The sign-in service is replaced at its dependency: what is asserted here is the
HTTP half - the token pair or the single-use code, the Negotiate challenge, the
rate limit, refusals carried to the sign-in page - because the service itself
is `tests/test_directory_sign_in.py`'s.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.api.routes.v1._directory_handoff import NO_TICKET, negotiate_token, return_url
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.main import app
from app.services import rate_limit
from app.services.directory.contract import DirectoryCredentialsRejected, TicketRejected
from app.services.session import SessionService

pytestmark = pytest.mark.anyio

_LDAP = f"{settings.API_V1_STR}/auth/ldap/login"
_KERBEROS = f"{settings.API_V1_STR}/auth/kerberos/login"


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        self._store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def getdel(self, key: str) -> str | None:
        return self._store.pop(key, None)


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), credential_version=2, is_active=True)


@pytest.fixture
def sign_in() -> MagicMock:
    service = MagicMock()
    service.require_kerberos = MagicMock()
    app.dependency_overrides[deps.get_directory_sign_in_service] = lambda: service
    return service


@pytest.fixture
def sessions(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    created = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(SessionService, "create_session", created)
    return created


@pytest.fixture(autouse=True)
def _reset_limiter():
    yield
    rate_limit.configure(None)


class TestLdapLogin:
    async def test_the_right_credentials_get_a_token_pair_and_a_session(
        self, client: AsyncClient, sign_in: MagicMock, sessions: AsyncMock
    ) -> None:
        user = _user()
        sign_in.sign_in_with_password = AsyncMock(return_value=user)

        resp = await client.post(_LDAP, json={"username": "jane", "password": " pw "})

        assert resp.status_code == 200
        assert {"access_token", "refresh_token"} <= resp.json().keys()
        assert sign_in.sign_in_with_password.await_args.args == ("jane", " pw ")
        assert sign_in.sign_in_with_password.await_args.kwargs == {"invitation_token": None}
        assert sessions.await_args.kwargs["user_id"] == user.id

    async def test_a_staged_invitation_rides_along_by_its_handle(
        self, client: AsyncClient, sign_in: MagicMock, sessions: AsyncMock
    ) -> None:
        redis = _FakeRedis()
        await redis.set("invitation:stage:h-1", "invite-token")
        app.dependency_overrides[deps.get_redis] = lambda: redis
        sign_in.sign_in_with_password = AsyncMock(return_value=_user())

        await client.post(
            _LDAP, json={"username": "jane", "password": "pw", "invitation_handle": "h-1"}
        )

        assert sign_in.sign_in_with_password.await_args.kwargs == {
            "invitation_token": "invite-token"
        }

    @pytest.mark.security
    async def test_wrong_credentials_are_a_401_that_says_nothing_more(
        self, client: AsyncClient, sign_in: MagicMock, sessions: AsyncMock
    ) -> None:
        sign_in.sign_in_with_password = AsyncMock(side_effect=DirectoryCredentialsRejected())

        resp = await client.post(_LDAP, json={"username": "jane", "password": "nope"})

        assert resp.status_code == 401
        assert resp.json()["error"]["message"] == "Invalid username or password"
        sessions.assert_not_awaited()

    @pytest.mark.security
    async def test_an_empty_password_is_refused_before_the_directory_is_asked(
        self, client: AsyncClient, sign_in: MagicMock
    ) -> None:
        sign_in.sign_in_with_password = AsyncMock()

        resp = await client.post(_LDAP, json={"username": "jane", "password": ""})

        assert resp.status_code == 422
        sign_in.sign_in_with_password.assert_not_awaited()

    @pytest.mark.security
    async def test_attempts_over_the_window_are_refused_with_429(
        self, client: AsyncClient, sign_in: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 3)
        counter = MagicMock()
        counter.count_in_window = AsyncMock(return_value=4)
        rate_limit.configure(counter)
        sign_in.sign_in_with_password = AsyncMock()

        resp = await client.post(_LDAP, json={"username": "jane", "password": "guess"})

        assert resp.status_code == 429
        sign_in.sign_in_with_password.assert_not_awaited()


class TestKerberosLogin:
    async def test_a_request_without_a_ticket_is_challenged(
        self, client: AsyncClient, sign_in: MagicMock
    ) -> None:
        resp = await client.get(_KERBEROS)

        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Negotiate"
        assert resp.headers["cache-control"] == "no-store"
        # What a browser with no ticket renders: straight back to the sign-in page.
        assert 'http-equiv="refresh"' in resp.text
        assert "/login?error=" in resp.text

    async def test_an_unconfigured_deployment_sends_no_challenge_at_all(
        self, client: AsyncClient, sign_in: MagicMock
    ) -> None:
        sign_in.require_kerberos = MagicMock(side_effect=NotFoundError(message="Unknown"))

        resp = await client.get(_KERBEROS)

        assert resp.status_code == 404
        assert "www-authenticate" not in resp.headers

    async def test_a_ticket_ends_at_the_frontend_with_a_code_and_mutual_auth(
        self, client: AsyncClient, sign_in: MagicMock, sessions: AsyncMock
    ) -> None:
        app.dependency_overrides[deps.get_redis] = _FakeRedis
        user = _user()
        sign_in.sign_in_with_ticket = AsyncMock(return_value=(user, b"server-token"))

        resp = await client.get(
            _KERBEROS,
            headers={"Authorization": f"Negotiate {base64.b64encode(b'ticket').decode()}"},
        )

        assert resp.status_code == 307
        location = urlparse(resp.headers["location"])
        assert location.path == "/auth/callback"
        assert "code" in parse_qs(location.query)
        assert resp.headers["www-authenticate"] == (
            f"Negotiate {base64.b64encode(b'server-token').decode()}"
        )
        assert sign_in.sign_in_with_ticket.await_args.args == (b"ticket",)
        # The session row carries the id the access token names, chosen up front.
        assert sessions.await_args.kwargs["session_id"] is not None

    async def test_the_desktop_shell_gets_its_deep_link(
        self, client: AsyncClient, sign_in: MagicMock, sessions: AsyncMock
    ) -> None:
        app.dependency_overrides[deps.get_redis] = _FakeRedis
        sign_in.sign_in_with_ticket = AsyncMock(return_value=(_user(), None))

        resp = await client.get(
            f"{_KERBEROS}?client=desktop&desktop_nonce=n-1",
            headers={"Authorization": f"Negotiate {base64.b64encode(b't').decode()}"},
        )

        assert resp.headers["location"].startswith(f"{settings.DESKTOP_DEEP_LINK_SCHEME}://")
        assert "desktop_nonce=n-1" in resp.headers["location"]
        assert "www-authenticate" not in resp.headers

    async def test_a_rejected_ticket_goes_back_to_the_sign_in_page_with_its_sentence(
        self, client: AsyncClient, sign_in: MagicMock, sessions: AsyncMock
    ) -> None:
        sign_in.sign_in_with_ticket = AsyncMock(side_effect=TicketRejected())

        resp = await client.get(
            _KERBEROS, headers={"Authorization": f"Negotiate {base64.b64encode(b't').decode()}"}
        )

        assert resp.status_code == 307
        query = parse_qs(urlparse(resp.headers["location"]).query)
        assert query["error"] == [TicketRejected.message]
        sessions.assert_not_awaited()

    async def test_an_unexpected_failure_is_logged_and_sent_back_generically(
        self, client: AsyncClient, sign_in: MagicMock
    ) -> None:
        sign_in.sign_in_with_ticket = AsyncMock(side_effect=RuntimeError("KDC at 10.0.0.5 said no"))

        resp = await client.get(
            _KERBEROS, headers={"Authorization": f"Negotiate {base64.b64encode(b't').decode()}"}
        )

        query = parse_qs(urlparse(resp.headers["location"]).query)
        assert query["error"] == ["Sign-in failed. Please try again."]

    async def test_an_invitation_handle_survives_the_challenge(
        self, client: AsyncClient, sign_in: MagicMock, sessions: AsyncMock
    ) -> None:
        redis = _FakeRedis()
        await redis.set("invitation:stage:h-2", "invite-token")
        app.dependency_overrides[deps.get_redis] = lambda: redis
        sign_in.sign_in_with_ticket = AsyncMock(return_value=(_user(), None))

        await client.get(
            f"{_KERBEROS}?invitation_handle=h-2",
            headers={"Authorization": f"Negotiate {base64.b64encode(b't').decode()}"},
        )

        assert sign_in.sign_in_with_ticket.await_args.kwargs == {"invitation_token": "invite-token"}


class TestNegotiateHeader:
    @pytest.mark.parametrize(
        "header",
        [None, "", "Bearer abc", "Basic YTpi", "Negotiate", "Negotiate    ", "Negotiate !!!"],
    )
    def test_anything_but_a_negotiate_token_is_no_ticket(self, header: str | None) -> None:
        assert negotiate_token(header) is None

    def test_the_scheme_is_case_insensitive(self) -> None:
        assert negotiate_token(f"negotiate {base64.b64encode(b'x').decode()}") == b"x"

    def test_the_console_is_the_default_return(self) -> None:
        assert return_url("c", client=None, desktop_nonce=None).endswith("/auth/callback?code=c")

    def test_the_no_ticket_sentence_is_the_one_the_challenge_renders(self) -> None:
        assert "Windows sign-in" in NO_TICKET
