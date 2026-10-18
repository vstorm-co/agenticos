"""The secrets API, through the app.

`tests/api/test_platform_routes.py` proves each of these routes is gated on
`connections:manage` and nothing else. What is left is what the routes
actually return - and the one thing that must never appear in any of it.
"""

from __future__ import annotations

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
from app.core.secret_kinds import SecretKind
from app.main import app

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_ORGANIZATION_ID = uuid.uuid4()
_SECRET_ID = uuid.uuid4()


def _row(**overrides: Any) -> MagicMock:
    row = MagicMock()
    row.id = _SECRET_ID
    row.name = "Weather API"
    row.description = "Used by the forecast capability"
    row.kind = SecretKind.API_KEY.value
    row.hint = "4242"
    # Who stored it and what it is holding up. Both are read off the row rather
    # than joined per request, so a route test has to carry them.
    row.created_by_user_id = None
    row.created_by_email = "owner@acme.test"
    row.created_by_avatar_url = None
    row.shared_with = 0
    row.used_by = []
    # What the key is for, and how far it reaches. Both are read off the row,
    # so a route test has to carry them.
    row.purpose = "openai"
    row.visibility = "org"
    row.owner_user_id = None
    row.owner_email = None
    row.created_at = datetime.now(UTC)
    row.updated_at = None
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list_secrets = AsyncMock(return_value=[_row()])
    stub.create = AsyncMock(return_value=_row())
    stub.update = AsyncMock(return_value=_row(name="Weather"))
    stub.delete = AsyncMock(return_value=None)
    return stub


@pytest.fixture
def client(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_secret_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(tail: str) -> str:
    return f"{settings.API_V1_STR}/secrets{tail}"


class TestListing:
    async def test_a_secret_is_identified_by_name_kind_and_hint(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(""))

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Weather API"
        assert body["items"][0]["kind"] == "api_key"
        assert body["items"][0]["hint"] == "4242"

    async def test_the_response_carries_nothing_that_could_be_a_value(self, client) -> None:
        """The listing is the surface a UI reads; the value is not on it."""
        async with client() as opened:
            response = await opened.get(_url(""))

        assert "value" not in response.json()["items"][0]
        assert "sealed_secret" not in response.json()["items"][0]

    async def test_the_kinds_endpoint_ships_a_form_schema_for_each_shape(self, client) -> None:
        """The frontend generates its forms from these rather than from a second list."""
        async with client() as opened:
            response = await opened.get(_url("/kinds"))

        assert response.status_code == 200
        kinds = {entry["kind"] for entry in response.json()["items"]}
        assert kinds == {
            "api_key",
            "azure_openai",
            "aws_credentials",
            "gcp_service_account",
            "github_oauth_app",
            "github_app",
            "google_oauth_app",
            "git_token",
            "entra_app",
            "openai_codex",
        }
        assert all(entry["json_schema"]["properties"] for entry in response.json()["items"])


class TestWriting:
    async def test_creating_passes_the_typed_value_through_and_returns_only_a_hint(
        self, client, service
    ) -> None:
        async with client() as opened:
            response = await opened.post(
                _url(""),
                json={
                    "name": "Weather API",
                    "value": {"kind": "api_key", "api_key": "wx-live-abcd4242"},
                },
            )

        assert response.status_code == 201
        assert "wx-live-abcd4242" not in response.text
        assert service.create.call_args.kwargs["value"].kind is SecretKind.API_KEY

    async def test_a_value_that_does_not_match_its_kind_is_refused_by_the_schema(
        self, client, service
    ) -> None:
        """The discriminated union is the validation; nothing reaches the service."""
        async with client() as opened:
            response = await opened.post(
                _url(""),
                json={"name": "AWS", "value": {"kind": "aws_credentials", "api_key": "sk"}},
            )

        assert response.status_code == 422
        assert service.create.await_count == 0

    async def test_the_keyless_shape_cannot_be_stored_as_a_secret(self, client) -> None:
        """ "No credential" is a state a provider can be in, not a secret to keep."""
        async with client() as opened:
            response = await opened.post(
                _url(""), json={"name": "Nothing", "value": {"kind": "none"}}
            )

        assert response.status_code == 422

    async def test_patching_forwards_only_what_was_sent(self, client, service) -> None:
        async with client() as opened:
            response = await opened.patch(_url(f"/{_SECRET_ID}"), json={"name": "Weather"})

        assert response.status_code == 200
        assert response.json()["name"] == "Weather"
        assert service.update.call_args.kwargs == {
            "name": "Weather",
            "description": None,
            "value": None,
        }

    async def test_deleting_answers_with_no_content(self, client, service) -> None:
        async with client() as opened:
            response = await opened.delete(_url(f"/{_SECRET_ID}"))

        assert response.status_code == 204
        assert service.delete.call_args.args[1] == _SECRET_ID


class TestSigningInWithChatGPT:
    """The one secret stored by finishing a sign-in rather than by posting it."""

    @pytest.fixture
    def codex(self) -> Iterator[MagicMock]:
        stub = MagicMock()
        stub.start_sign_in = AsyncMock(
            return_value="https://auth.openai.com/oauth/authorize?state=s"
        )
        stub.create = AsyncMock(
            return_value=_row(
                kind=SecretKind.OPENAI_CODEX.value, purpose="openai_codex", hint="abcd"
            )
        )
        stub.reconnect = AsyncMock(
            return_value=_row(
                kind=SecretKind.OPENAI_CODEX.value, purpose="openai_codex", hint="abcd"
            )
        )
        app.dependency_overrides[deps.get_openai_codex_service] = lambda: stub
        yield stub

    async def test_starting_answers_with_where_to_send_the_person(self, client, codex) -> None:
        async with client() as opened:
            response = await opened.post(_url("/openai-codex/sign-in"))

        assert response.status_code == 200
        assert response.json() == {
            "authorization_url": "https://auth.openai.com/oauth/authorize?state=s"
        }

    @pytest.mark.security
    async def test_a_sign_in_cannot_be_posted_as_a_value(self, client, service) -> None:
        """Only finishing the flow writes one: posted as a value it would be any
        pair of tokens, bound to nobody's sign-in."""
        value = {
            "kind": "openai_codex",
            "access_token": "a" * 40,
            "refresh_token": "r" * 40,
            "account_id": "acct",
            "expires_at": "2030-01-01T00:00:00Z",
        }
        async with client() as opened:
            created = await opened.post(_url(""), json={"name": "Mine", "value": value})
            rotated = await opened.patch(_url(f"/{uuid.uuid4()}"), json={"value": value})

        assert (created.status_code, rotated.status_code) == (422, 422)
        service.create.assert_not_called()

    async def test_a_viewer_may_start_one_to_reconnect_a_secret_granted_to_them(
        self, client, codex
    ) -> None:
        """Starting stores nothing; the reconnect it ends in checks the grant."""
        app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
            user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.VIEWER
        )
        async with client() as opened:
            response = await opened.post(_url("/openai-codex/sign-in"))

        assert response.status_code == 200

    async def test_finishing_stores_it_private_unless_told_otherwise(self, client, codex) -> None:
        callback = "http://localhost:1455/auth/callback?code=the-code&state=s"
        async with client() as opened:
            response = await opened.post(
                _url("/openai-codex"), json={"name": "My ChatGPT", "callback_url": callback}
            )

        assert response.status_code == 201
        assert response.json()["kind"] == "openai_codex"
        assert "the-code" not in response.text
        assert codex.create.call_args.kwargs == {
            "callback_url": callback,
            "name": "My ChatGPT",
            "description": None,
            "visibility": "private",
        }

    async def test_reconnecting_signs_in_again_in_place(self, client, codex) -> None:
        async with client() as opened:
            response = await opened.put(
                _url(f"/{_SECRET_ID}/openai-codex"), json={"callback_url": "?code=c&state=s"}
            )

        assert response.status_code == 200
        assert codex.reconnect.call_args.args[1] == _SECRET_ID
        assert codex.reconnect.call_args.kwargs == {"callback_url": "?code=c&state=s"}

    async def test_an_empty_paste_never_reaches_the_service(self, client, codex) -> None:
        async with client() as opened:
            response = await opened.post(
                _url("/openai-codex"), json={"name": "My ChatGPT", "callback_url": ""}
            )

        assert response.status_code == 422
        assert codex.create.await_count == 0
