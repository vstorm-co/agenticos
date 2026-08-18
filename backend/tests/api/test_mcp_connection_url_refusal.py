"""A blocked MCP server URL, through the app.

The guard itself is covered by `tests/test_ssrf.py`; what is asserted here is
how its refusal *arrives*. `SSRFBlockedError` subclasses `ValueError`, which no
handler in `app/api/exception_handlers.py` maps, so every one of these requests
used to answer 500 "An unexpected error occurred" with `details: null` and a
traceback in the log - a crash report for the ordinary case of a self-hosted
deployment pasting a `localhost` address (#861).

The service is the real one; only the session and Redis are mocked. Validation
refuses before any row is read, so nothing here reaches the database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

# An address that is refused without resolving anything: an IP literal, so no
# test in this file touches DNS.
_LOOPBACK_URL = "http://127.0.0.1:3000/mcp"

# The same refusal, asked for by a URL that carries a credential in both places
# a URL can carry one.
_URL_WITH_SECRETS = "http://console:hunter2@10.0.0.5:3000/mcp?token=sh-secret-value"

# A third place, and the one the standard library used to read back out: a port
# that is not a number. `urlsplit` parses it lazily and quotes what it could not
# cast, so this shape - not the two above - is what an uncontrolled `str(exc)`
# echoes.
_URL_WITH_A_SECRET_FOR_A_PORT = "http://mcp.example.com:client_secret=sh-port-secret/mcp"


@pytest.fixture
def client(mock_db_session: Any, mock_redis: MagicMock) -> Iterator[Any]:
    user = MagicMock()
    user.id = uuid.uuid4()
    context = AuthContext(user_id=user.id, organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
    # An AsyncMock's children are AsyncMocks, so `execute(...).scalar_one_or_none()`
    # would hand a repository a coroutine nobody awaits.
    mock_db_session.execute.return_value = MagicMock()
    app.dependency_overrides[deps.get_db_session] = lambda: mock_db_session
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_auth_context] = lambda: context

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


class TestTheRefusalReachesTheOperator:
    async def test_a_personal_connection_to_a_loopback_url_is_refused_with_a_400(
        self, client
    ) -> None:
        async with client() as opened:
            response = await opened.post(
                f"{settings.API_V1_STR}/me/mcp-connections",
                json={"name": "internal", "url": _LOOPBACK_URL},
            )

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "BAD_REQUEST"
        assert error["details"] == {"field": "url"}

    async def test_an_organization_connection_to_a_loopback_url_is_refused_with_a_400(
        self, client
    ) -> None:
        async with client() as opened:
            response = await opened.post(
                f"{settings.API_V1_STR}/mcp-connections",
                json={"name": "internal", "url": _LOOPBACK_URL},
            )

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "BAD_REQUEST"
        assert error["details"] == {"field": "url"}

    async def test_starting_oauth_against_a_loopback_url_is_refused_with_a_400(
        self, client
    ) -> None:
        """The OAuth flow validates before it discovers anything, so this is the
        same refusal one call earlier - and it too used to be a 500."""
        async with client() as opened:
            response = await opened.post(
                f"{settings.API_V1_STR}/me/mcp-connections/oauth/start",
                json={"name": "internal", "url": _LOOPBACK_URL},
            )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BAD_REQUEST"

    async def test_the_refusal_says_what_the_reader_can_act_on(self, client) -> None:
        """A message naming the host is the difference between "fix the address"
        and "the platform is broken"."""
        async with client() as opened:
            response = await opened.post(
                f"{settings.API_V1_STR}/me/mcp-connections",
                json={"name": "internal", "url": _LOOPBACK_URL},
            )

        message = response.json()["error"]["message"]
        assert "127.0.0.1" in message
        assert message != "An unexpected error occurred"


class TestTheRefusalQuotesNoSecret:
    async def test_neither_userinfo_nor_a_query_token_appears_in_the_body(self, client) -> None:
        """`details` names the field, and the message names a host at most.

        A URL carries a key in its query string and a password in its userinfo,
        and the URL being refused may have been written by the party being
        refused (`.claude/rules/exceptions-security.md`).
        """
        async with client() as opened:
            response = await opened.post(
                f"{settings.API_V1_STR}/me/mcp-connections",
                json={"name": "internal", "url": _URL_WITH_SECRETS},
            )

        assert response.status_code == 400
        assert "hunter2" not in response.text
        assert "sh-secret-value" not in response.text
        assert response.json()["error"]["details"] == {"field": "url"}

    async def test_a_secret_parked_where_the_port_belongs_is_not_read_back(self, client) -> None:
        """The refusal for this one is written by `urlsplit`, not by us.

        It answers a port it cannot cast with `Port could not be cast to integer
        value as '<what you sent>'`, so a boundary that quotes any `ValueError`
        echoes whatever was parked there - which is why `_checked_url` catches
        `UrlRefusedError` and `validate_webhook_url` raises its own for this.
        """
        async with client() as opened:
            response = await opened.post(
                f"{settings.API_V1_STR}/me/mcp-connections",
                json={"name": "internal", "url": _URL_WITH_A_SECRET_FOR_A_PORT},
            )

        assert response.status_code == 400
        assert "sh-port-secret" not in response.text
        assert response.json()["error"]["details"] == {"field": "url"}
