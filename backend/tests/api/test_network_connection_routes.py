"""The network API keeps enrollment private and reads out of the action paths."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.repositories import network_connection_repo
from app.schemas.network_connection import (
    NetworkConnectionList,
    NetworkConnectionRead,
    NetworkEnrollmentRead,
    NetworkPeerList,
    NetworkPeerRead,
)
from app.services.network_connections import facade

pytestmark = pytest.mark.anyio

# Parametrize values become xdist collection ids, so keep these stable across
# workers. Runtime-only test data can still use uuid4().
_ORG_ID = uuid.UUID("c7e9b8a4-48eb-4a5f-ae15-58b3b294cecb")
_USER_ID = uuid.UUID("ca71134c-7b79-4a49-a8e1-dfd65b7f7f2b")
_SESSION_ID = uuid.UUID("818c2585-948f-459b-9cce-b3d55fb86dca")
_CONNECTION_ID = uuid.UUID("c48f5ac1-b465-40c9-b1ca-2f3e8f4876f5")
_LOGIN_URL = "https://login.tailscale.com/a/secret-session-url"
_V1 = settings.API_V1_STR


def _read(**overrides: Any) -> NetworkConnectionRead:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "id": _CONNECTION_ID,
        "organization_id": _ORG_ID,
        "owner_user_id": _USER_ID,
        "scope": "user",
        "visibility": "private",
        "name": "My devices",
        "desired_state": "active",
        "auth_state": "sign_in_required",
        "runtime_state": "starting",
        "cleanup_state": "none",
        "policy_generation": 2,
        "enrollment_expires_at": now + timedelta(minutes=10),
        "tailnet_name": None,
        "node_id": None,
        "peers": [],
        "last_seen_at": None,
        "last_error_code": None,
        "can_manage": True,
        "created_at": now,
        "updated_at": now,
    }
    return NetworkConnectionRead(**(values | overrides))


@pytest.fixture
def caller() -> AuthContext:
    return AuthContext(user_id=_USER_ID, organization_id=_ORG_ID, role=OrgRoleName.OWNER)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list = AsyncMock(
        return_value=NetworkConnectionList(items=[_read()], total=1, available=True)
    )
    stub.get = AsyncMock(return_value=_read())
    stub.create = AsyncMock(return_value=_read(desired_state="paused", auth_state="not_connected"))
    stub.connect = AsyncMock(return_value=_read())
    stub.enrollment = AsyncMock(
        return_value=NetworkEnrollmentRead(
            attempt_id=uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            login_url=_LOGIN_URL,
        )
    )
    stub.peers = AsyncMock(
        return_value=NetworkPeerList(
            items=[
                NetworkPeerRead(
                    id="peer-1",
                    hostname="laptop",
                    dns_name="laptop.example.ts.net.",
                    ips=["100.90.0.1"],
                    online=True,
                    os="windows",
                )
            ],
            observed_at=datetime.now(UTC),
        )
    )
    stub.refresh = AsyncMock(return_value=_read())
    stub.pause = AsyncMock(return_value=_read(desired_state="paused", runtime_state="stopped"))
    stub.revoke = AsyncMock(return_value=_read(desired_state="revoked"))
    return stub


@pytest.fixture
def authenticated_client(
    client: AsyncClient, caller: AuthContext, service: MagicMock
) -> AsyncClient:
    app.dependency_overrides[deps.get_auth_context] = lambda: caller
    app.dependency_overrides[deps.get_current_session_id] = lambda: _SESSION_ID
    app.dependency_overrides[deps.get_network_connection_service] = lambda: service
    return client


@pytest.mark.parametrize(
    ("path", "payload", "service_method", "status_code"),
    [
        ("", {"name": "My devices", "scope": "user"}, "create", 201),
        (f"/{_CONNECTION_ID}/connect", None, "connect", 202),
        (f"/{_CONNECTION_ID}/refresh", None, "refresh", 202),
        (f"/{_CONNECTION_ID}/pause", None, "pause", 200),
        (f"/{_CONNECTION_ID}/revoke", None, "revoke", 200),
    ],
)
async def test_management_posts_forward_the_caller_session_and_connection(
    authenticated_client: AsyncClient,
    caller: AuthContext,
    service: MagicMock,
    path: str,
    payload: dict[str, str] | None,
    service_method: str,
    status_code: int,
) -> None:
    request = {"json": payload} if payload is not None else {}
    response = await authenticated_client.post(f"{_V1}/network-connections{path}", **request)

    assert response.status_code == status_code
    call = getattr(service, service_method).await_args
    assert call.args[0] is caller
    assert call.kwargs["session_id"] == _SESSION_ID
    if service_method == "create":
        assert call.args[1].name == "My devices"
        assert call.args[1].scope == "user"
    else:
        assert call.kwargs["connection_id"] == _CONNECTION_ID


@pytest.mark.security
async def test_private_reads_are_not_cached_do_not_start_actions_or_leak_the_login_url(
    authenticated_client: AsyncClient,
    service: MagicMock,
) -> None:
    """A read may expose enrollment metadata only on its session-bound route."""
    leaking_row = _read().model_dump(mode="json") | {
        "login_url": _LOGIN_URL,
        "login_payload": "sealed-login-payload",
        "state_payload": "sealed-node-payload",
    }
    service.list.return_value = {"items": [leaking_row], "total": 1, "available": True}
    service.get.return_value = leaking_row

    responses = [
        await authenticated_client.get(f"{_V1}/network-connections"),
        await authenticated_client.get(f"{_V1}/network-connections/{_CONNECTION_ID}"),
        await authenticated_client.get(f"{_V1}/network-connections/{_CONNECTION_ID}/enrollment"),
        await authenticated_client.get(f"{_V1}/network-connections/{_CONNECTION_ID}/peers"),
    ]

    assert all(response.status_code == 200 for response in responses)
    assert all(response.headers.get("cache-control") == "no-store" for response in responses)
    assert _LOGIN_URL not in responses[0].text
    assert _LOGIN_URL not in responses[1].text
    assert "login_url" not in responses[0].json()["items"][0]
    assert "login_url" not in responses[1].json()
    assert responses[2].json()["login_url"] == _LOGIN_URL
    assert responses[3].json()["items"][0]["id"] == "peer-1"

    for action in ("create", "connect", "refresh", "pause", "revoke"):
        getattr(service, action).assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("case", ["foreign", "expired"])
async def test_a_foreign_or_expired_session_is_refused_before_loading_a_connection(
    client: AsyncClient,
    caller: AuthContext,
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """The API uses the real facade so a stale browser cannot reach the row."""
    app.dependency_overrides[deps.get_auth_context] = lambda: caller
    app.dependency_overrides[deps.get_current_session_id] = lambda: _SESSION_ID
    session = SimpleNamespace(
        user_id=uuid.uuid4() if case == "foreign" else _USER_ID,
        is_active=True,
        impersonator_user_id=None,
        expires_at=(
            datetime.now(UTC) - timedelta(seconds=1)
            if case == "expired"
            else datetime.now(UTC) + timedelta(hours=1)
        ),
    )
    get_session = AsyncMock(return_value=session)
    get_connection = AsyncMock()
    monkeypatch.setattr(facade.session_repo, "get_by_id", get_session)
    monkeypatch.setattr(network_connection_repo, "get_by_id", get_connection)

    response = await client.get(f"{_V1}/network-connections/{_CONNECTION_ID}")

    assert response.status_code == 403
    get_session.assert_awaited_once_with(mock_db_session, _SESSION_ID)
    get_connection.assert_not_awaited()


@pytest.mark.security
async def test_membership_change_cannot_release_an_enrollment_url(
    client: AsyncClient,
    caller: AuthContext,
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal at the membership fence must happen before the bearer URL is read."""
    app.dependency_overrides[deps.get_auth_context] = lambda: caller
    app.dependency_overrides[deps.get_current_session_id] = lambda: _SESSION_ID
    session = SimpleNamespace(
        user_id=_USER_ID,
        is_active=True,
        impersonator_user_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    get_session = AsyncMock(return_value=session)
    check_membership = AsyncMock(
        side_effect=AuthorizationError(message="Your membership has changed; sign in again")
    )
    get_connection = AsyncMock()
    monkeypatch.setattr(facade.session_repo, "get_by_id", get_session)
    monkeypatch.setattr(facade, "guard_member", check_membership)
    monkeypatch.setattr(network_connection_repo, "get_by_id", get_connection)

    response = await client.get(f"{_V1}/network-connections/{_CONNECTION_ID}/enrollment")

    assert response.status_code == 403
    assert _LOGIN_URL not in response.text
    check_membership.assert_awaited_once_with(
        mock_db_session,
        organization_id=_ORG_ID,
        user_id=_USER_ID,
        admission=False,
    )
    get_connection.assert_not_awaited()
