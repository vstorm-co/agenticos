"""The sandbox connections API, through the app.

`tests/api/test_platform_routes.py` proves each of these routes is gated on
`connections:manage` and nothing else - the same permission the vault carries,
because whoever edits these decides which host an agent's shell runs on. What is
left is what the routes actually return, and the one thing none of them may ever
carry: the credential. A response holding the service token would be a token in a
browser, and that token opens a session that runs commands on the host.
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
from app.main import app
from app.schemas.sandbox_connection import SandboxConnectionRead

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()
_CONNECTION_ID = uuid.uuid4()
_SECRET_ID = uuid.uuid4()


def _read(**overrides: Any) -> SandboxConnectionRead:
    fields: dict[str, Any] = {
        "id": _CONNECTION_ID,
        "name": "Local Docker",
        "kind": "docker",
        "base_url": "http://sandboxd:8080",
        "secret_id": _SECRET_ID,
        "default_runtime": "python",
        "is_default": True,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "updated_at": None,
    }
    return SandboxConnectionRead(**{**fields, **overrides})


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list_connections = AsyncMock(return_value=[_read()])
    stub.create = AsyncMock(return_value=_read())
    stub.update = AsyncMock(return_value=_read(name="Big box"))
    stub.delete = AsyncMock(return_value=None)
    stub.sessions = AsyncMock(
        return_value={
            "sessions": [
                {
                    "session_id": "xc-1",
                    "runtime": "python",
                    "alive": True,
                    "state": "running",
                    "created_at": 1.0,
                    "last_activity": 2.0,
                    "idle_seconds": 3.0,
                    "agent_id": str(uuid.uuid4()),
                    "scope": "conversation",
                }
            ],
            "limit": 20,
            "open_limit": 100,
            "tenant_limit": 5,
            "host_session_count": 12,
            "host_open_count": 30,
        }
    )
    stub.session_events = AsyncMock(
        return_value={
            "events": [{"seq": 1, "at": 1.0, "op": "exec", "target": "python run.py", "ok": True}],
            "latest_seq": 1,
        }
    )
    stub.policy = AsyncMock(
        return_value={
            "kind": "docker",
            "runtimes": [{"alias": "python", "image": "python:3.12-slim", "mem_limit": "512m"}],
            "default_runtime": "python",
            "max_sessions_per_tenant": 5,
        }
    )
    return stub


@pytest.fixture
def client(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_sandbox_connection_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(tail: str) -> str:
    return f"{settings.API_V1_STR}/sandbox-connections{tail}"


class TestListing:
    async def test_a_connection_is_identified_by_name_kind_and_address(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(""))

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Local Docker"
        assert body["items"][0]["kind"] == "docker"
        assert body["items"][0]["base_url"] == "http://sandboxd:8080"

    async def test_the_credential_is_a_reference_and_never_a_value(self, client) -> None:
        """The whole reason `secret_id` is a UUID in this schema."""
        async with client() as opened:
            response = await opened.get(_url(""))

        item = response.json()["items"][0]
        assert item["secret_id"] == str(_SECRET_ID)
        assert not {"token", "api_key", "secret"} & set(item)


class TestRegistering:
    async def test_a_new_connection_comes_back_with_its_id(self, client) -> None:
        async with client() as opened:
            response = await opened.post(
                _url(""),
                json={
                    "name": "Local Docker",
                    "kind": "docker",
                    "base_url": "http://sandboxd:8080",
                    "secret_id": str(_SECRET_ID),
                },
            )

        assert response.status_code == 201
        assert response.json()["id"] == str(_CONNECTION_ID)

    async def test_a_kind_outside_the_two_that_exist_never_reaches_the_service(
        self, client, service
    ) -> None:
        """The schema refuses it, so an unknown kind is a 422 rather than a row."""
        async with client() as opened:
            response = await opened.post(_url(""), json={"name": "Whatever", "kind": "kubernetes"})

        assert response.status_code == 422
        service.create.assert_not_called()


class TestEditing:
    async def test_renaming_returns_the_new_name(self, client) -> None:
        async with client() as opened:
            response = await opened.patch(_url(f"/{_CONNECTION_ID}"), json={"name": "Big box"})

        assert response.status_code == 200
        assert response.json()["name"] == "Big box"

    async def test_forgetting_a_host_answers_no_content(self, client, service) -> None:
        async with client() as opened:
            response = await opened.delete(_url(f"/{_CONNECTION_ID}"))

        assert response.status_code == 204
        service.delete.assert_awaited_once()


class TestThePolicy:
    async def test_what_the_service_allows_is_proxied_through(self, client) -> None:
        """Proxied rather than fetched by the browser: reaching the service needs
        a token that must never be in one."""
        async with client() as opened:
            response = await opened.get(_url(f"/{_CONNECTION_ID}/policy"))

        assert response.status_code == 200
        body = response.json()
        assert [runtime["alias"] for runtime in body["runtimes"]] == ["python"]
        assert body["runtimes"][0]["mem_limit"] == "512m"
        assert body["max_sessions_per_tenant"] == 5

    async def test_the_policy_response_carries_no_credential_either(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(f"/{_CONNECTION_ID}/policy"))

        assert "token" not in response.text.lower()


class TestTheSessions:
    async def test_this_organizations_sandboxes_come_back_with_their_ceilings(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(f"/{_CONNECTION_ID}/sessions"))

        assert response.status_code == 200
        body = response.json()
        assert body["sessions"][0]["session_id"] == "xc-1"
        assert body["tenant_limit"] == 5

    async def test_the_host_wide_counts_ride_alongside_the_ceilings(self, client) -> None:
        """Both numerators reach the response through `response_model`, so the two
        host ceilings become dividable the way the per-tenant one already is."""
        async with client() as opened:
            response = await opened.get(_url(f"/{_CONNECTION_ID}/sessions"))

        body = response.json()
        assert body["host_session_count"] == 12
        assert body["host_open_count"] == 30

    async def test_a_row_names_the_agent_rather_than_only_a_hex_string(self, client) -> None:
        """Read from `agent_workspaces`; the id is deliberately not decoded."""
        async with client() as opened:
            response = await opened.get(_url(f"/{_CONNECTION_ID}/sessions"))

        assert response.json()["sessions"][0]["scope"] == "conversation"

    async def test_the_tenant_label_is_not_echoed_back(self, client) -> None:
        """Every row is this organization's by then, so the field would only be a
        second place for that to be believed."""
        async with client() as opened:
            response = await opened.get(_url(f"/{_CONNECTION_ID}/sessions"))

        assert "tenant" not in response.json()["sessions"][0]

    async def test_usage_is_off_unless_asked_for(self, client, service) -> None:
        async with client() as opened:
            await opened.get(_url(f"/{_CONNECTION_ID}/sessions"))
        assert service.sessions.await_args.kwargs == {"usage": False}

        async with client() as opened:
            await opened.get(_url(f"/{_CONNECTION_ID}/sessions"), params={"usage": "true"})
        assert service.sessions.await_args.kwargs == {"usage": True}

    async def test_the_activity_log_says_what_was_done_and_how_it_went(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(f"/{_CONNECTION_ID}/sessions/xc-1/events"))

        assert response.status_code == 200
        body = response.json()
        assert body["events"][0]["op"] == "exec"
        assert body["latest_seq"] == 1

    async def test_polling_passes_the_sequence_it_already_has(self, client, service) -> None:
        async with client() as opened:
            await opened.get(_url(f"/{_CONNECTION_ID}/sessions/xc-1/events"), params={"after": 7})

        assert service.session_events.await_args.kwargs == {"after": 7}

    async def test_a_negative_sequence_never_reaches_the_service(self, client, service) -> None:
        async with client() as opened:
            response = await opened.get(
                _url(f"/{_CONNECTION_ID}/sessions/xc-1/events"), params={"after": -1}
            )

        assert response.status_code == 422
        service.session_events.assert_not_called()
