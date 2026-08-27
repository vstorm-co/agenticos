"""Where a magic link lands, and what may be signed into one.

The link answered `/dashboard` for everybody, so which of the three doors
somebody came through still decided where they ended up - the drift #121 removed
on the roles axis and #135 on the provider axis, on the last door that had it
(#1214).

It cannot take #135's fix. That one carries the path in `sessionStorage`, which
is allowed because the OAuth round trip starts and ends in the same tab on this
origin; a magic link is followed from an email - another tab, often another
application, sometimes another browser - where that store is empty by
construction. So the path travels *in the token*, signed, and the request refuses
anything that is not a path on this deployment rather than storing it and
checking later: a token that can be made to hold an arbitrary string is a
stored-redirect surface even when the read is checked.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session, get_redis, get_session_service, get_user_service
from app.core.config import settings
from app.core.security import create_magic_link_token
from app.main import app
from app.services.user import UserService

pytestmark = pytest.mark.anyio

REQUEST = f"{settings.API_V1_STR}/auth/magic-link/request"
VERIFY = f"{settings.API_V1_STR}/auth/magic-link/verify"


class _User:
    def __init__(self) -> None:
        self.id = uuid4()
        self.email = "kacper@example.com"
        self.full_name = "Kacper"
        self.is_active = True


@pytest.fixture
async def client(mock_redis: MagicMock, mock_db_session) -> AsyncGenerator[AsyncClient, None]:
    service = MagicMock()
    service.issue_magic_link_token = AsyncMock(return_value=None)
    service.consume_magic_link_token = AsyncMock(return_value=(_User(), None))
    sessions = MagicMock()
    sessions.create_session = AsyncMock()
    app.dependency_overrides[get_user_service] = lambda: service
    app.dependency_overrides[get_session_service] = lambda: sessions
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.service = service  # ty: ignore[unresolved-attribute]
        yield ac
    app.dependency_overrides.clear()


class TestWhatMayBeSignedIntoALink:
    async def test_a_path_on_this_deployment_reaches_the_service(self, client: AsyncClient) -> None:
        response = await client.post(
            REQUEST, json={"email": "kacper@example.com", "return_to": "/agents/a-1"}
        )

        assert response.status_code == 200
        service = client.service  # ty: ignore[unresolved-attribute]
        assert service.issue_magic_link_token.await_args.kwargs["return_to"] == "/agents/a-1"

    async def test_a_request_with_no_path_asks_for_none(self, client: AsyncClient) -> None:
        response = await client.post(REQUEST, json={"email": "kacper@example.com"})

        assert response.status_code == 200
        service = client.service  # ty: ignore[unresolved-attribute]
        assert service.issue_magic_link_token.await_args.kwargs["return_to"] is None

    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("https://evil.example", id="absolute"),
            pytest.param("//evil.example", id="protocol_relative"),
            pytest.param("/\\evil.example", id="backslash"),
            pytest.param("/\tevil", id="control_character"),
            pytest.param("agents", id="relative"),
        ],
    )
    async def test_anything_else_is_refused_before_it_is_signed(
        self, client: AsyncClient, path: str
    ) -> None:
        """Refused at the request, not merely ignored at the landing: the value
        is signed into a token that arrives by email, so the shortest life it can
        have is none."""
        response = await client.post(
            REQUEST, json={"email": "kacper@example.com", "return_to": path}
        )

        assert response.status_code == 422
        assert [problem["field"] for problem in response.json()["error"]["details"]["fields"]] == [
            "return_to"
        ]
        service = client.service  # ty: ignore[unresolved-attribute]
        service.issue_magic_link_token.assert_not_awaited()


class TestTheLandingIsToldWhereItWasHeaded:
    async def test_the_verify_answers_with_the_path(self, client: AsyncClient) -> None:
        service = client.service  # ty: ignore[unresolved-attribute]
        service.consume_magic_link_token = AsyncMock(return_value=(_User(), "/agents/a-1"))

        response = await client.post(VERIFY, json={"token": "a" * 20})

        assert response.status_code == 200
        assert response.json()["return_to"] == "/agents/a-1"

    async def test_a_link_minted_without_one_answers_null(self, client: AsyncClient) -> None:
        response = await client.post(VERIFY, json={"token": "a" * 20})

        assert response.status_code == 200
        assert response.json()["return_to"] is None


class TestTheTokenCarriesIt:
    async def test_the_path_survives_the_round_trip(self, mock_db_session) -> None:
        """Signed, so it cannot be edited between the email and the landing."""
        user = _User()
        service = UserService(mock_db_session)
        token = create_magic_link_token(subject=str(user.id), return_to="/agents/a-1")

        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(service, "get_by_id", AsyncMock(return_value=user))
            consumed, return_to = await service.consume_magic_link_token(token)

        assert consumed is user
        assert return_to == "/agents/a-1"

    async def test_a_token_with_no_claim_answers_none(self, mock_db_session) -> None:
        user = _User()
        service = UserService(mock_db_session)
        token = create_magic_link_token(subject=str(user.id))

        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(service, "get_by_id", AsyncMock(return_value=user))
            _, return_to = await service.consume_magic_link_token(token)

        assert return_to is None
